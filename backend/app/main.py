import os
import shutil
import tempfile
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.ingest import ingest_document
from app.query import query_document, stream_query
from app.domain_router import validate_domain
from app.config import ALLOWED_EXTENSIONS

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
        "endpoints": ["/health", "/ingest", "/query", "/stream"],
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

        with open(tmp_path, "wb") as f:
            f.write(content)

        # Full pipeline: parse → detect domain if needed → chunk → embed → store
        return ingest_document(tmp_path, domain or None)

    except ValueError as e:
        # Raised for unreadable/unsupported content — a client problem, not a server one
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# ── /query endpoint ──
# Accepts a question + domain, runs RAG pipeline, returns answer + sources.

class QueryRequest(BaseModel):
    question: str
    domain: str


@app.post("/query")
def query_endpoint(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not validate_domain(req.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {req.domain}. Valid: legal, finance, healthcare, enterprise",
        )

    # Retrieve relevant chunks → build prompt → call LLM → return answer
    result = query_document(req.question, req.domain)
    return result


# ── /stream endpoint ──
# Same as /query but streams the answer token-by-token as SSE, giving the
# frontend a live "typing" effect instead of one delayed blob.
#
# Note this is POST, so the browser's EventSource API cannot consume it —
# EventSource only issues GET requests. The frontend reads it with
# fetch() + response.body.getReader() instead. We keep POST because the
# question belongs in a request body, not in a URL query string.

@app.post("/stream")
async def stream_endpoint(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="Question cannot be empty")

    if not validate_domain(req.domain):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid domain: {req.domain}. Valid: legal, finance, healthcare, enterprise",
        )

    return StreamingResponse(
        stream_query(req.question, req.domain),
        media_type="text/event-stream",
    )
