# Agentic RAG — Document Intelligence Platform

AI-powered document analysis platform that automatically detects document domains and provides structured analysis using Retrieval-Augmented Generation.

## Architecture

```
┌────────────┐     ┌──────────────────────────────────────────┐
│            │     │              Backend (FastAPI)            │
│  Next.js   │────▶│                                          │
│  Frontend  │◀────│  Upload ─▶ Parse ─▶ Chunk ─▶ Embed ─▶   │
│            │ SSE │                                  FAISS   │
└────────────┘     │  Query ─▶ Retrieve ─▶ Domain Prompt ─▶   │
                   │                          Groq LLM ─▶ SSE │
                   └──────────────────────────────────────────┘
```

Documents are stored in a separate FAISS index per domain, so a legal query
only ever searches legal documents.

## Supported Domains

| Domain | Use Cases |
|---|---|
| Legal | Contract analysis, compliance checks, clause extraction |
| Finance | Risk analysis, regulatory review, audit support |
| Healthcare | Medical research summarization, clinical study analysis |
| Enterprise | Policy Q&A, knowledge base search, training docs |

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, LangChain |
| LLM | Groq API (`openai/gpt-oss-120b`, free tier) |
| Embeddings | sentence-transformers (BAAI/bge-small-en-v1.5) |
| Vector Store | FAISS (local, one index per domain) |
| Doc Parsing | PyMuPDF, python-docx |
| Frontend | Next.js 14, Tailwind CSS, Shadcn/UI |
| Streaming | Server-Sent Events (SSE) |

## Setup

### Prerequisites
- Conda (Anaconda/Miniconda)
- Node.js 18+ (for frontend)
- Groq API key (free at https://console.groq.com)

### Backend
```bash
conda create -n agentic-rag python=3.11 -y
conda activate agentic-rag
cd backend
pip install -r requirements.txt
cp .env.example .env   # then add your GROQ_API_KEY
uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Environment Variables

See `backend/.env.example` for required variables.

## Build Status

**Phase 0 — Environment Setup** ✅
- [x] Conda environment
- [x] Dependencies installed
- [x] Folder structure created
- [x] Git initialized
- [x] README created

**Phase 1 — Backend Core** ✅
- [x] config.py
- [x] ingest.py — PDF/DOCX/TXT parsing, tables, chunking
- [x] domain_router.py — keyword-based domain detection
- [x] prompt_templates.py — four domain prompts
- [x] query.py — FAISS retrieval + Groq RAG chain
- [x] main.py — `/health`, `/ingest`, `/query`, `/stream` endpoints

**Phase 2 — Frontend** ⏳ Pending

**Phase 3 — Polish** ⏳ Pending

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/ingest` | Upload a document (multipart: `file`, optional `domain`) |
| POST | `/query` | Ask a question, get answer + sources |
| POST | `/stream` | Same as `/query` but streams tokens over SSE |

Interactive docs at http://127.0.0.1:8000/docs while the server is running.

## Future Improvements

- Summarize figures/charts with a vision model (`qwen/qwen3.6-27b` on Groq)
- Upgrade to Qwen3-Embedding-0.6B for better retrieval accuracy
- Add multi-document cross-referencing
- User authentication and document history
- Deployment with Docker
