# IPO Analyser — a multi-agent reader for Indian offer documents

Upload a DRHP or RHP (the 300–600 page document a company files before its IPO) and get back a scored, cited report: what the company does, whether the numbers hold up, what the risk factors add up to, where the money is going, and what it is being sued over. Every statement links to the page it came from.

Built on an earlier general document Q&A app, which is still here at `/general`.

> **Educational, not investment advice.** Every figure comes from the offer document as read by AI models, which make mistakes. The rating is a transparent rubric, not a recommendation.

## How it works

```
Upload a DRHP / RHP
        │
Agent 0  Parser, no LLM: table of contents → sections, risk headings,
         summary financials, and a hybrid search index
        │
        ├─ Agent 1  Risk factors      scores all 50-80 risk factors 1-5
        ├─ Agent 2  Financial health  ratios in Python, LLM explains
        ├─ Agent 5  Legal & approvals cases, amounts vs net worth
        ├─ Agent 3  Business & promoters   stake, pledges, governance
        └─ Agent 4  Offer & proceeds  fresh issue vs offer for sale, peers
        │
Rubric   0-100 score and rating, in Python, with a reason per point
        │
Agent 7  Writes the summary, bull and bear cases, from the agents' output only
        │
Report + chat, every claim citing its page
```

The pipeline is a **LangGraph** graph. Agents that read the parsed data or the PDF start immediately; the two that search the index wait for it. They run side by side where the models allow it, and results are saved as each finishes.

### Design decisions worth knowing

- **The LLMs never do arithmetic.** Ratios, percentages, totals and the score are computed in Python. The models extract and explain.
- **Every number is checked.** A figure an agent reports must appear in the text it was shown; if it doesn't, it's dropped with a warning. Page citations the model invents are removed the same way.
- **Deterministic wherever possible.** Whether promoter shares are pledged, and whether a case is *against* the company or *filed by* it, are decided by reading the document's own standard wording, not the model's judgement. Both were getting misread.
- **Free-tier rate limits are designed around.** Each agent has its own Groq model, calls are paced against a token budget per minute (including Qwen's separate output-token limit), and every call is retried when Groq asks for a wait.
- **Work is never repeated.** Each agent's output is saved, so a failed analysis resumes where it stopped and re-analysing the same file costs nothing.

## The agents

| # | Agent | Reads | Produces | Model |
|---|---|---|---|---|
| 0 | Parser | Table of contents, then each section | Sections with page ranges, risk headings, summary financials, search index | none |
| 1 | Risk factors | The numbered risk headings | Every risk scored 1–5, categorised, ranked | `gpt-oss-20b` |
| 2 | Financial health | Summary financial statements | 16 ratios per period, a 7-part scorecard, red flags, an explanation | `qwen3.8-27b` |
| 3 | Business & promoters | Our Business, Promoters, Capital Structure | What it does, strengths, weaknesses, promoter stake, pledges, governance | `gpt-oss-120b` |
| 4 | Offer & use of proceeds | The Offer, Objects, Basis for Price | Fresh issue vs offer for sale, dilution, where the money goes, listed peers | `qwen3.8-27b` |
| 5 | Legal & approvals | Outstanding Litigation, Government Approvals | Cases by type and party, claims as a share of net worth, missing approvals | `gpt-oss-20b` |
| — | Rubric | The agents' output | 0–100 score, rating, breakdown, knockout rules | none (Python) |
| 7 | Synthesis | Only the agents' output | Summary, bull and bear cases, what to check | `gpt-oss-120b` |

The score is out of 100: financial health 30, risk factors 20, business and promoters 20, legal 15, offer structure 15. Ratings are **Leans Subscribe** (65+), **Neutral** (45–64) and **Leans Avoid**. Weak financial health, or a criminal or SEBI case against the company, caps the rating at Neutral however well the rest scores.

## What the reports look like

Each report has a summary with bull and bear cases, the score breakdown with every deduction explained, and five tabs of detail (financials, risk register, business and promoters, offer, legal). Page badges open the PDF at that page. A chat tab answers follow-up questions from the analysis and the document.

## Accuracy

`backend/checks/expected.json` holds facts read by hand from the sample documents, each with its page. The checker compares them with what the agents produced, using no tokens:

```bash
python checks/verify_accuracy.py
```

It covers parsed figures (revenue, profit, cash flow), extracted facts (share counts, proceeds, promoter holdings, peer P/E), computed metrics (dilution, offer-for-sale share) and the tricky cases, such as a criminal complaint *filed by* a promoter not counting as one *against* him.

## Tech stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph 0.5 (pinned; newer releases need langchain-core 1.x) |
| Backend | Python 3.11, FastAPI, LangChain 0.3 |
| Models | Groq free tier: `gpt-oss-120b`, `gpt-oss-20b`, `qwen3.8-27b` |
| Structured output | Pydantic schemas, JSON mode, one repair retry |
| Search | FAISS (cosine) + BM25 keywords, merged by reciprocal rank fusion |
| Embeddings | `BAAI/bge-small-en-v1.5`, local on CPU |
| Parsing | PyMuPDF, python-docx |
| Frontend | Next.js 16 (App Router), React 19, Tailwind v4, shadcn/ui |
| Streaming | Server-Sent Events over `fetch` |

## Setup

### Prerequisites
- Conda (Anaconda or Miniconda)
- Node.js 20+
- A free Groq API key from https://console.groq.com

### Get the code
```bash
git clone https://github.com/samoutlier/Agentic-RAG.git
cd Agentic-RAG
```

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

## How to run

Start the backend from `backend/`:
```bash
python -m uvicorn app.main:app --reload
```
The first start downloads the embedding model (~130 MB). `python -m uvicorn` is used instead of plain `uvicorn` because it also works on Windows machines where Application Control blocks pip-generated `.exe` launchers.

Start the frontend from `frontend/`, in a second terminal:
```bash
npm run dev
```

Open **http://localhost:3000** and drop in a DRHP or RHP. Use `localhost` rather than `127.0.0.1`: the backend's CORS setting only allows `http://localhost:3000`.

Interactive API docs: http://127.0.0.1:8000/docs

To run one analysis from the terminal instead, without the frontend:
```bash
python try_agents.py "../samples/Jindal Supreme RHP.PDF"
```

### How long it takes

| | First time | Same document again |
|---|---|---|
| Parsing | 5–15s | 5–15s |
| Search index (CPU) | 3–4 min | reused |
| Agents and report | 2–4 min, mostly waiting on rate limits | reused |

About 45,000 Groq tokens per document, spread across three models. Free-tier daily limits allow several documents a day.

## Sample documents

`samples/` has the DRHP and RHP of two real IPOs, with very different profiles: ESDS Software Solution (a cloud and data-centre company, high margins, past losses) and Jindal Supreme (India) (steel pipes, thin margins, negative operating cash flow in its latest year). Analysing both shows how the rubric separates them.

## API

| Endpoint | Purpose |
|---|---|
| `POST /ipo/analyses` | Upload a PDF; returns a job id (`fresh=true` redoes every agent) |
| `GET /ipo/jobs/{job_id}?after=N` | Progress: step statuses and messages after the first N |
| `GET /ipo/analyses` | Finished analyses, newest first |
| `GET /ipo/analyses/{document_id}` | One analysis: every agent's output |
| `GET /ipo/analyses/{document_id}/document` | The uploaded PDF (citations link to `#page=`) |
| `POST /ipo/analyses/{document_id}/rerun` | Analyse the saved PDF again, reusing finished agents |
| `POST /ipo/analyses/{document_id}/chat` | Ask about the report and document; streams the answer |
| `DELETE /ipo/analyses/{document_id}` | Delete everything saved for a document |

The earlier general Q&A endpoints (`/ingest`, `/documents`, `/query`, `/stream`) still work and drive the page at `/general`.

## Environment variables

**Backend** (`backend/.env`, see `backend/.env.example`)

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | *(required)* | Groq API key |
| `RISK_AGENT_MODEL` | `openai/gpt-oss-20b` | Agent 1 |
| `FINANCIAL_AGENT_MODEL` | `qwen/qwen3.8-27b` | Agent 2 |
| `BUSINESS_AGENT_MODEL` | `openai/gpt-oss-120b` | Agent 3 (the 20b model breaks this agent's nested JSON) |
| `OFFER_AGENT_MODEL` | `qwen/qwen3.8-27b` | Agent 4 |
| `LEGAL_AGENT_MODEL` | `openai/gpt-oss-20b` | Agent 5 |
| `SYNTHESIS_AGENT_MODEL` | `openai/gpt-oss-120b` | Agent 7 |
| `GROQ_TOKENS_PER_MINUTE` | `8000` | Free-tier budget each model is paced against |
| `QWEN_OUTPUT_TOKENS_PER_MINUTE` | `1000` | Qwen's separate output-token limit |
| `IPO_DATA_DIR` | `ipo_data` | Where documents, indexes and results are saved |
| `IPO_CHUNK_SIZE` / `IPO_CHUNK_OVERLAP` | `800` / `100` | Chunking for offer documents |
| `LLM_MODEL` | `openai/gpt-oss-120b` | Answers chat questions |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Changing it means deleting `ipo_data/` and re-analysing |
| `MAX_UPLOAD_MB` / `MAX_QUESTION_CHARS` | `50` / `2000` | Request size limits |

Settings for the general Q&A app (`CHUNK_SIZE`, `TOP_K_RESULTS`, `FAISS_INDEX_DIR`, `CLASSIFIER_MODEL`, `HISTORY_*`) are unchanged and listed in `.env.example`.

**Frontend** (`frontend/.env.local`)

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_URL` | `http://127.0.0.1:8000` | Backend URL |

## Known limitations

- **Only what the document says.** No market data, no subscription figures, no anchor-investor list. There's no P/E at the issue price because the price band is published after the DRHP and RHP.
- **Some offer documents can't be read.** One sample's restated financial statements are drawn as shapes rather than text; the summary financial statements are used instead. A document with no readable table of contents is rejected.
- **The models vary between runs.** Extraction of long legal chapters is the least stable part: one run found a GST claim in a footnote that another missed.
- **The rubric's weights are judgement calls,** written down in `backend/app/agents/rubric.py` so they can be argued with and changed.
- **Unfinished jobs live in memory.** A server restart loses a running job, though everything already saved is kept and re-uploading resumes.
- **Industry-blind thresholds.** "A good margin" is treated the same for a data-centre operator and a steel pipe maker.

## Build status

Steps 1–18 of the build plan are complete: parser, the five analysis agents, rubric, synthesis, background jobs, API, upload and progress UI, report page, chat and accuracy checks.

## Possible next steps

- Compare two IPOs, or a DRHP against its later RHP, side by side
- Accept the price band once announced, to compute P/E against peers
- Industry-aware thresholds, from the peer figures the document already gives
- A faster index (quantised embeddings, or reuse across documents from the same issuer)
