import os
from pathlib import Path
from dotenv import load_dotenv

# Loading the .env file from backend
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# Setting the env variables
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
LLM_MODEL = os.getenv("LLM_MODEL", "llama-3.1-70b-versatile")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.1"))
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5")
CHROMA_PERSIST_DIR = os.getenv("CHROMA_PERSIST_DIR", "./chroma_data")

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

# Allowed file types 
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt"}
