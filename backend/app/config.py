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
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "20"))
MAX_QUESTION_CHARS = int(os.getenv("MAX_QUESTION_CHARS", "2000"))
