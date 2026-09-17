import logging
import os
import shutil
import tempfile
from typing import Literal

import groq
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.ingest import ingest_document, list_documents, delete_document, DocumentError
from app.query import query_document, stream_query, describe_llm_error
from app.domain_router import validate_domain
from app.config import ALLOWED_EXTENSIONS, MAX_UPLOAD_MB, MAX_QUESTION_CHARS

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
        "endpoints": ["/health", "/ingest", "/documents", "/query", "/stream"],
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
