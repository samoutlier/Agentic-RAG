import os
from pathlib import Path
from dotenv import load_dotenv

#It is to load the .env file from backend
BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env")

# Setting the env variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL    = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
# Smaller, separate model for classifying uploads into a domain
CLASSIFIER_MODEL = os.getenv("CLASSIFIER_MODEL", "openai/gpt-oss-20b")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
# Resolved against backend/, not the folder uvicorn happens to be started from
FAISS_INDEX_DIR = str(BACKEND_DIR / os.getenv("FAISS_INDEX_DIR", "faiss_data"))

# I have creaetd 4 domains here 
DOMAIN_COLLECTIONS = {
    "legal": "legal_docs",
    "finance": "finance_docs",
    "healthcare": "healthcare_docs",
    "enterprise": "enterprise_docs",
}

# Chunking size
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

#To retreie only top k results
TOP_K_RESULTS = int(os.getenv("TOP_K_RESULTS", "5"))

# Follow-up questions: how much recent chat is included in the prompt.
# One answer can be ~1,300 tokens and Groq's free tier allows 8,000 tokens
# per minute, so history is capped by message count and trimmed per message.
HISTORY_MAX_MESSAGES = int(os.getenv("HISTORY_MAX_MESSAGES", "6"))
HISTORY_MAX_CHARS = int(os.getenv("HISTORY_MAX_CHARS", "1500"))

# Allowed file types 
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}

# Size limits, checked by the API before any processing.
# The frontend checks the same limits first so users get instant feedback.
# DRHPs and RHPs are often 10–30 MB, hence the generous upload limit.
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "2000"))

# ── IPO document analysis (DRHP / RHP) ──
# Each analysis agent has its own Groq model. Groq rate-limits every model
# separately (free tier: 8,000 tokens per minute and 200,000 per day each),
# so spreading the agents over three models gives three separate budgets.
RISK_AGENT_MODEL = os.getenv("RISK_AGENT_MODEL", "openai/gpt-oss-20b")
FINANCIAL_AGENT_MODEL = os.getenv("FINANCIAL_AGENT_MODEL", "qwen/qwen3.8-27b")
# gpt-oss-20b often breaks the nesting of this agent's JSON (lists of cited
# claims); the 120b model gets it right and has its own budget
BUSINESS_AGENT_MODEL = os.getenv("BUSINESS_AGENT_MODEL", "openai/gpt-oss-120b")
OFFER_AGENT_MODEL = os.getenv("OFFER_AGENT_MODEL", "qwen/qwen3.8-27b")
LEGAL_AGENT_MODEL = os.getenv("LEGAL_AGENT_MODEL", "openai/gpt-oss-20b")
SYNTHESIS_AGENT_MODEL = os.getenv("SYNTHESIS_AGENT_MODEL", "openai/gpt-oss-120b")

# Tokens each model may use per minute. Agent calls are paced against this
# budget, so the pipeline waits instead of hitting Groq's rate limit.
GROQ_TOKENS_PER_MINUTE = int(os.getenv("GROQ_TOKENS_PER_MINUTE", "8000"))
# Some models also cap output tokens per minute. Groq's free tier gives
# qwen3.8-27b only 1,000, so its replies are capped at that length too.
GROQ_OUTPUT_TOKENS_PER_MINUTE = {
    "qwen/qwen3.8-27b": int(os.getenv("QWEN_OUTPUT_TOKENS_PER_MINUTE", "1000")),
}

# Where each analysed document's parsed data, search index and report are
# saved (one folder per document), resolved against backend/
IPO_DATA_DIR = str(BACKEND_DIR / os.getenv("IPO_DATA_DIR", "ipo_data"))

# Offer documents are long and dense, so their chunks are bigger than the
# general ones above: more context per search result, fewer chunks to embed.
# 800 characters stays within the embedding model's 256-token limit even
# for number-heavy table text, so no chunk gets cut off.
IPO_CHUNK_SIZE = int(os.getenv("IPO_CHUNK_SIZE", "800"))
IPO_CHUNK_OVERLAP = int(os.getenv("IPO_CHUNK_OVERLAP", "100"))
