import logging
import os
import shutil
import tempfile
from typing import Literal

import groq
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.ingest import ingest_document, list_documents, delete_document, DocumentError
from app.query import query_document, stream_query, describe_llm_error
from app.domain_router import validate_domain
from app.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, MAX_QUESTION_CHARS
from app.agents import jobs
from app.drhp.parser import document_folder, document_id

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Agentic RAG",
    description="AI-powered document intelligence platform",
    version="0.1.0",
)

# CORS: allows the Next.js frontend (port 3000) to call this API.
# Without this, the browser blocks cross-origin requests.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    """Landing route — points callers at the interactive docs."""
    return {
        "service": "Agentic RAG",
        "docs": "/docs",
        "endpoints": ["/health", "/ingest", "/documents", "/query", "/stream",
                      "/ipo/analyses", "/ipo/jobs/{job_id}", "/ipo/analyses/{document_id}"],
    }


@app.get("/health")
def health_check():
    return {"status": "ok", "message": "Agentic RAG backend is running"}


# ── /ingest endpoint ──
# Accepts a file upload + optional domain override.
# Flow: save temp file → detect/validate domain → run full ingest pipeline

@app.post("/ingest")
async def ingest_endpoint(
    file: UploadFile = File(...),              # the uploaded document
    domain: str = Form(default=""),            # optional: user picks domain
):
    # basename strips any directory components a client might send
    # (e.g. "../../evil.txt"), keeping the write inside our temp dir.
    filename = os.path.basename(file.filename or "")
    if not filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {ext}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # If the caller supplied a domain, it must be one we know about.
    # If they didn't, ingest_document() auto-detects it after parsing.
    if domain and not validate_domain(domain):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {domain}. Valid: legal, finance, healthcare, enterprise",
        )

    # Save the upload to a temp file so our parsers can read it from disk.
    tmp_dir = tempfile.mkdtemp()
    tmp_path = os.path.join(tmp_dir, filename)
    try:
        content = await file.read()
        if not content:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")

        size_mb = len(content) / (1024 * 1024)
        if size_mb > MAX_UPLOAD_MB:
            raise HTTPException(
                status_code=413,  # "Payload Too Large"
                detail=f"File is too large ({size_mb:.1f} MB). The limit is {MAX_UPLOAD_MB} MB.",
            )

        with open(tmp_path, "wb") as f:
            f.write(content)

        # Full pipeline: parse → detect domain if needed → chunk → embed → store
        return ingest_document(tmp_path, domain or None)

    except DocumentError as e:
        # Unreadable, encrypted or empty file: a problem with the upload, not the server
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── /documents endpoints ──
# List what's stored, and delete a document from its domain.

@app.get("/documents")
def documents_endpoint():
    """Every indexed document: filename, domain, chunk count and page count."""
    return list_documents()


@app.delete("/documents/{domain}/{filename}")
def delete_document_endpoint(domain: str, filename: str):
    if not validate_domain(domain):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {domain}. Valid: legal, finance, healthcare, enterprise",
        )

    removed = delete_document(domain, filename)
    if removed == 0:
        raise HTTPException(
            status_code=404,
            detail=f'No document named "{filename}" in the {domain} documents.',
        )
    return {"filename": filename, "domain": domain, "chunks_removed": removed}


# ── /query endpoint ──
# Accepts a question + domain (+ optional chat history), runs the RAG
# pipeline, returns answer + sources.

class ChatTurn(BaseModel):
    """One earlier message in the conversation."""
    role: Literal["user", "assistant"]
    content: str = Field(max_length=20_000)


class QueryRequest(BaseModel):
    question: str
    domain: str
    # Earlier messages in this chat, oldest first. Optional, so a one-off
    # question (from curl or /docs) still works without it. The list size is
    # capped because this comes straight from the client.
    history: list[ChatTurn] = Field(default_factory=list, max_length=50)


def validate_query(req: QueryRequest) -> None:
    """Checks shared by /query and /stream. Raises HTTP 400 with a clear message."""
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if len(req.question) > MAX_QUESTION_CHARS:
        raise HTTPException(
            status_code=400,
            detail=f"Question is too long ({len(req.question):,} characters). "
                   f"The limit is {MAX_QUESTION_CHARS:,}.",
        )

    if not validate_domain(req.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {req.domain}. Valid: legal, finance, healthcare, enterprise",
        )


@app.post("/query")
def query_endpoint(req: QueryRequest):
    validate_query(req)

    # Retrieve relevant chunks → build prompt → call LLM → return answer
    history = [turn.model_dump() for turn in req.history]
    try:
        return query_document(req.question, req.domain, history)
    except groq.APIError as exc:
        status, message = describe_llm_error(exc)
        if status != 429:
            logger.exception("LLM request failed")
        raise HTTPException(status_code=status, detail=message)


# ── /stream endpoint ──
# Same as /query but streams the answer token-by-token as SSE, giving the
# frontend a live "typing" effect instead of one delayed blob.
#
# Note this is POST, so the browser's EventSource API cannot consume it —
# EventSource only issues GET requests. The frontend reads it with
# fetch() + response.body.getReader() instead. We keep POST because the
# question belongs in a request body, not in a URL query string.
#
# If the client disconnects (e.g. the user presses Stop), Starlette cancels
# this generator, which closes the Groq request so no more tokens are spent.

@app.post("/stream")
async def stream_endpoint(req: QueryRequest):
    validate_query(req)

    history = [turn.model_dump() for turn in req.history]
    return StreamingResponse(
        stream_query(req.question, req.domain, history),
        media_type="text/event-stream",
    )


# ── IPO analysis endpoints ──
# An analysis takes minutes, so it runs as a background job:
#   POST /ipo/analyses          upload a DRHP / RHP; returns a job id at once
#   GET  /ipo/jobs/{job_id}     progress, polled by the browser every few seconds
#   GET  /ipo/analyses          finished analyses, newest first
#   GET  /ipo/analyses/{id}     one finished analysis: every agent's output
#   GET  /ipo/analyses/{id}/document   the uploaded PDF, so citations can open it
#   POST /ipo/analyses/{id}/rerun      analyse the saved PDF again (resumes)
#   DELETE /ipo/analyses/{id}   delete everything saved for a document

@app.post("/ipo/analyses", status_code=202)  # 202 Accepted: queued, not finished
async def create_analysis(
    file: UploadFile = File(...),
    fresh: bool = Form(default=False),  # true: ignore saved agent outputs and redo them all
):
    filename = os.path.basename(file.filename or "")
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Please upload the DRHP or RHP as a PDF file")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(status_code=413, detail=f"File is too large ({size_mb:.1f} MB). The limit is {MAX_UPLOAD_MB} MB.")

    # The document id comes from the file's name and contents, so it's
    # computed on a temporary copy that keeps the original name
    tmp_dir = tempfile.mkdtemp()
    try:
        tmp_path = os.path.join(tmp_dir, filename)
        with open(tmp_path, "wb") as f:
            f.write(content)
        doc_id = document_id(tmp_path)
        if fresh and jobs.active_job(doc_id):
            raise HTTPException(status_code=409, detail="This document is being analysed right now")
        folder = document_folder(doc_id)
        folder.mkdir(parents=True, exist_ok=True)
        shutil.move(tmp_path, folder / filename)
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    if fresh:
        jobs.clear_results(doc_id)
    job = jobs.submit(doc_id, filename)
    return {"job_id": job.id, "document_id": doc_id, "status": job.status}


@app.get("/ipo/jobs/{job_id}")
def job_endpoint(job_id: str, after: int = 0):
    """A job's status, the status of each step, and progress messages
    after the first `after` (send back event_count to get only new ones)."""
    job = jobs.get_job(job_id)
    if job is None:
        # Jobs live in memory, so they're gone after a restart; finished
        # analyses are still listed at /ipo/analyses
        raise HTTPException(status_code=404, detail="No such job (the server may have restarted)")
    return jobs.job_view(job, after)


@app.get("/ipo/analyses")
def analyses_endpoint():
    return jobs.list_analyses()


@app.get("/ipo/analyses/{doc_id}")
def analysis_endpoint(doc_id: str):
    analysis = jobs.load_analysis(os.path.basename(doc_id))
    if analysis is None:
        raise HTTPException(status_code=404, detail="No finished analysis for this document")
    return analysis


@app.get("/ipo/analyses/{doc_id}/document")
def analysis_document_endpoint(doc_id: str):
    """The uploaded PDF, shown inline: a citation links to it with #page=N
    and the browser's PDF viewer opens that page."""
    pdf = jobs.document_pdf(os.path.basename(doc_id))
    if pdf is None:
        raise HTTPException(status_code=404, detail="No document saved for this analysis")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name, content_disposition_type="inline")


@app.post("/ipo/analyses/{doc_id}/rerun", status_code=202)
def rerun_analysis_endpoint(doc_id: str, fresh: bool = False):
    """Analyse a saved document again. Saved agent outputs are reused unless
    fresh is true, so a failed analysis resumes where it stopped."""
    doc_id = os.path.basename(doc_id)
    pdf = jobs.document_pdf(doc_id)
    if pdf is None:
        raise HTTPException(status_code=404, detail="This document is no longer saved. Please upload it again.")
    if fresh:
        if jobs.active_job(doc_id):
            raise HTTPException(status_code=409, detail="This document is being analysed right now")
        jobs.clear_results(doc_id)
    job = jobs.submit(doc_id, pdf.name)
    return {"job_id": job.id, "document_id": doc_id, "status": job.status}


@app.delete("/ipo/analyses/{doc_id}")
def delete_analysis_endpoint(doc_id: str):
    doc_id = os.path.basename(doc_id)  # a folder name, never a path
    if jobs.active_job(doc_id):
        raise HTTPException(status_code=409, detail="This document is being analysed right now")
    if not jobs.delete_analysis(doc_id):
        raise HTTPException(status_code=404, detail="No such document")
    return {"document_id": doc_id, "deleted": True}
