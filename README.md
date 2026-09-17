# Agentic RAG — Document Intelligence Platform

Upload legal, finance, healthcare, or enterprise documents and ask questions about them. The system classifies each document into a domain, retrieves the most relevant passages, and streams back an answer from an LLM that cites the source file and page.

## Architecture

```
┌────────────┐     ┌──────────────────────────────────────────┐
│            │     │              Backend (FastAPI)           │
│  Next.js   │────▶│                                          │
│  Frontend  │◀────│  Upload ─▶ Parse ─▶ Classify domain ─▶   │
│            │ SSE │          Chunk ─▶ Embed ─▶ FAISS         │
└────────────┘     │                                          │
                   │  Question + chat history ─▶ Retrieve ─▶  │
                   │  Domain prompt ─▶ Groq LLM ─▶ SSE stream │
                   └──────────────────────────────────────────┘
```

- **Ingestion:** PDF, DOCX, and TXT files are parsed, with each table written once in its original position. A small LLM reads the opening of the document and classifies it as legal, finance, healthcare, or enterprise; if that call fails, keyword matching decides instead. The text is split into ~500-character chunks, embedded locally, and stored in a separate FAISS index per domain, so a legal question only ever searches legal documents.
- **Querying:** the question is embedded and matched against its domain's index. The top 5 chunks, the recent conversation, and a domain-specific prompt go to the LLM, and the answer streams back token by token with its sources.
- **Follow-up questions:** the last 3 question/answer pairs are sent with each question, so "which of those is riskiest?" works. **New chat** clears this memory.

## Features

- Upload by drag and drop, with automatic domain detection and a manual override
- Documents list per domain, loaded from the server, with delete
- Streaming answers with a **Stop** button, which also stops the LLM request on the server
- Source citations with file, page, and match score; weaker matches are folded away, and a note appears when even the best match is weak
- Clear messages for bad files, size limits, rate limits, and connection problems

## Supported Domains

| Domain | Use Cases |
|---|---|
| Legal | Contract analysis, compliance checks, clause extraction |
| Finance | Risk analysis, regulatory review, audit support |
| Healthcare | Medical research summarization, clinical study analysis |
| Enterprise | Policy Q&A, knowledge base search, training docs, and anything that fits no other domain |

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, LangChain |
| LLM (answers) | Groq API, `openai/gpt-oss-120b` (free tier) |
| LLM (domain classification) | Groq API, `openai/gpt-oss-20b`, with a keyword-matching fallback |
| Embeddings | sentence-transformers (`BAAI/bge-small-en-v1.5`, runs locally on CPU) |
| Vector store | FAISS (local, one index per domain) |
| Document parsing | PyMuPDF, python-docx |
| Frontend | Next.js 16 (App Router), React 19, Tailwind CSS v4, shadcn/ui |
| Streaming | Server-Sent Events over `fetch` |

## Setup

### Prerequisites
- Conda (Anaconda or Miniconda)
- Node.js 20+
- A free Groq API key from https://console.groq.com

### Backend
```bash
conda create -n agentic-rag python=3.11 -y
conda activate agentic-rag
cd backend
pip install -r requirements.txt
```
Copy `backend/.env.example` to `backend/.env` and set `GROQ_API_KEY`. The server refuses to start without it.

### Frontend
```bash
cd frontend
npm install
```
Copy `frontend/.env.example` to `frontend/.env.local`. The default points at `http://127.0.0.1:8000`.

## How to Run

Start the backend from the `backend/` folder:
```bash
python -m uvicorn app.main:app --reload
```
The first start downloads the embedding model (~130 MB). `python -m uvicorn` is used instead of plain `uvicorn` because it also works on Windows machines where Application Control blocks pip-generated `.exe` launchers.

Start the frontend from the `frontend/` folder, in a second terminal:
```bash
npm run dev
```

Open **http://localhost:3000**. Use `localhost` rather than `127.0.0.1`: the backend's CORS setting only allows `http://localhost:3000`.

Interactive API docs: http://127.0.0.1:8000/docs

## Try It With the Sample Documents

The `samples/` folder has one fictional document per domain, each with facts you can check:

| File | Domain | Try asking | Then follow up with |
|---|---|---|---|
| `legal_software_license_agreement.txt` | Legal | How long is the initial term, and how does renewal work? | How much notice is needed to stop that? |
| `finance_quarterly_report.pdf` | Finance | What was net profit in Q3 FY2026, and how did it change? | What is the biggest risk that could hurt it? |
| `healthcare_clinical_trial_summary.pdf` | Healthcare | How much did Veltrozan lower systolic blood pressure vs placebo? | What side effects did patients have on it? |
| `enterprise_remote_work_leave_policy.docx` | Enterprise | How many days of annual leave do employees get? | And what about sick leave? |

Ask something a document doesn't cover (e.g. "What is the CEO's salary?"): the model is instructed to say so rather than invent an answer.

## Environment Variables

**Backend** (`backend/.env`, see `backend/.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Model that answers questions |
| `LLM_TEMPERATURE` | `0.1` | Low values keep answers factual |
| `CLASSIFIER_MODEL` | `openai/gpt-oss-20b` | Model that classifies uploads. Groq rate-limits each model separately, so this doesn't use the answer model's quota |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Changing it requires deleting `backend/faiss_data/` and re-uploading |
| `FAISS_INDEX_DIR` | `faiss_data` | Index location, relative to `backend/` |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | `500` / `50` | Chunking, in characters |
| `TOP_K_RESULTS` | `5` | Chunks retrieved per question |
| `HISTORY_MAX_MESSAGES` / `HISTORY_MAX_CHARS` | `6` / `1500` | How much conversation reaches the prompt |
| `MAX_UPLOAD_MB` / `MAX_QUESTION_CHARS` | `20` / `2000` | Request size limits |

**Frontend** (`frontend/.env.local`, see `frontend/.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Backend URL |

## API Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/ingest` | Upload a document. Multipart form: `file`, optional `domain` (omit to auto-detect) |
| GET | `/documents` | List stored documents: `filename`, `domain`, `chunks`, `pages` |
| DELETE | `/documents/{domain}/{filename}` | Delete a document from its domain (404 if it doesn't exist) |
| POST | `/query` | Ask a question and get `{answer, sources}` |
| POST | `/stream` | Same as `/query`, but streams `sources`, `token`, `done`, or `error` events over SSE |

`/ingest` returns the chosen domain and how it was chosen: `detected_by` is `"user"`, `"llm"`, or `"keywords"` (the fallback):
```json
{ "filename": "finance_quarterly_report.pdf", "domain": "finance", "detected_by": "llm", "pages_parsed": 2, "chunks_stored": 4 }
```

`/query` and `/stream` take this JSON body. `history` is optional:
```json
{
  "question": "Which of those carries the biggest risk?",
  "domain": "legal",
  "history": [
    { "role": "user", "content": "What are the borrower's obligations?" },
    { "role": "assistant", "content": "..." }
  ]
}
```

## Limits and Error Handling

- **Uploads:** PDF, DOCX, or TXT up to 20 MB. Corrupted, password-protected, and image-only (scanned) PDFs are rejected with a message explaining why. Text files saved in Windows-1252 encoding are read correctly.
- **Domain classification:** if the classifier model is rate-limited, unreachable, or gives an unclear reply, the upload still succeeds using keyword matching, and the UI asks you to check the domain.
- **Questions:** up to 2,000 characters. Empty questions and unknown domains are rejected.
- **LLM failures:** a rate limit, a rejected API key, or no connection to Groq each produce a specific message. During streaming these arrive as an `error` event, because the HTTP status has already been sent.
- **Groq free tier:** limits apply per API key and per model, and can change. At the time of writing, the key used in development allowed about 8,000 tokens per minute and 1,000 requests per day for each model. One question costs roughly 1,500–3,000 tokens, so rapid-fire questions can hit the limit. Wait a minute and retry, or press **Stop** on answers you don't need.

## Build Status

**Phase 0 — Environment Setup** ✅

**Phase 1 — Backend Core** ✅
- [x] `config.py`, `ingest.py`, `domain_router.py`, `prompt_templates.py`, `query.py`, `main.py`

**Phase 2 — Frontend** ✅
- [x] Next.js scaffold, Tailwind, shadcn/ui
- [x] Root layout, domain tabs, file upload with auto-detect
- [x] Streaming chat window with follow-up question memory
- [x] Source citations (file, page, match %)
- [x] End-to-end test of all four domains with the sample documents

**Phase 3 — Polish** 🔧 In progress
- [x] Step 27: Error handling (bad files, size limits, empty/long questions, LLM failures)
- [x] LLM-based domain classification with keyword fallback
- [x] Step 28: Stop button, search/write loading states, weaker-match folding, scroll that respects reading
- [x] PDF tables stored once, in reading order
- [x] List and delete documents
- [ ] Step 29: README setup instructions and demo GIF
- [ ] Step 30: Final GitHub push

## Known Limitations

- **Four fixed domains.** A document that fits none of them (e.g. a machine-learning research paper) is filed under Enterprise. Uncheck auto-detect to choose the domain yourself.
- **Relevance can't be judged from match scores alone.** In testing, clearly relevant passages scored as low as 55% in one document while unrelated ones reached 60% in another, so no passages are dropped from the prompt; weaker matches are only folded away in the sources list.
- **Follow-up search leans on the previous question**, which can rank passages from the previous topic slightly higher after a topic change. Use **New chat** when switching topics.
- **Chat history lives in the browser tab**: refreshing the page clears it. Uploaded documents persist on the server.
- **Documents indexed before the table fix** still contain duplicated table text. Re-upload them to re-index with the current parser.

## Future Improvements

- Summarize figures and charts with a vision model (e.g. `qwen/qwen3.6-27b` on Groq)
- Rewrite follow-up questions with an LLM before searching, instead of prepending the previous question
- Upgrade embeddings to Qwen3-Embedding-0.6B
- Docker deployment
