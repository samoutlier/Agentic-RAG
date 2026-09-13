import fitz
from docx import Document
from pathlib import Path
from langchain.text_splitter import RecursiveCharacterTextSplitter
import chromadb
from sentence_transformers import SentenceTransformer
from app.config import (
    CHUNK_SIZE, CHUNK_OVERLAP, ALLOWED_EXTENSIONS,
    EMBEDDING_MODEL, CHROMA_PERSIST_DIR, DOMAIN_COLLECTIONS,
)


#Different Types of Parsing Document logic starts here 

def extract_tables_from_page(page: fitz.Page) -> str:
    """It extracts tables from a PDF page as formatted text."""
    tables = page.find_tables()
    if not tables.tables:
        return ""
    table_texts = []
    for table in tables:
        rows = table.extract()
        formatted = []
        for row in rows:
            cells = [str(cell) if cell else "" for cell in row]
            formatted.append(" | ".join(cells))
        table_texts.append("\n".join(formatted))
    return "\n\n[TABLE]\n" + "\n[TABLE]\n".join(table_texts) + "\n[/TABLE]\n"


def parse_pdf(file_path: str) -> list[dict]:
    """It extracts text and tables per page."""
    doc = fitz.open(file_path)
    pages = []
    for page_num, page in enumerate(doc, start=1):
        parts = []

        text = page.get_text().strip()
        if text:
            parts.append(text)

        table_text = extract_tables_from_page(page)
        if table_text:
            parts.append(table_text)

        combined = "\n\n".join(parts)
        if combined:
            pages.append({"text": combined, "page": page_num})

    doc.close()
    return pages


def parse_docx(file_path: str) -> list[dict]:
    """It extracts text and tables from a DOCX file."""
    doc = Document(file_path)
    parts = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    for table in doc.tables:
        rows = []
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            rows.append(" | ".join(cells))
        if rows:
            parts.append("[TABLE]\n" + "\n".join(rows) + "\n[/TABLE]")

    if not parts:
        return []
    return [{"text": "\n\n".join(parts), "page": 1}]

 
def parse_txt(file_path: str) -> list[dict]:
    """It reads a plain text file."""
    text = Path(file_path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [{"text": text, "page": 1}]

#Main Parsing Document Function 

def parse_document(file_path: str) -> list[dict]:
    """It will route to the correct parser based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    parser = {".pdf": parse_pdf, ".docx": parse_docx, ".txt": parse_txt}
    return parser[ext](file_path)


#  Chunking 

splitter = RecursiveCharacterTextSplitter(
    chunk_size=CHUNK_SIZE,
    chunk_overlap=CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)


def chunk_document(pages: list[dict], filename: str) -> list[dict]:
    """Split parsed pages into smaller chunks with metadata."""
    chunks = []
    chunk_id = 0
    for page in pages:
        splits = splitter.split_text(page["text"])
        for split_text in splits:
            chunks.append({
                "text": split_text,
                "metadata": {
                    "filename": filename,
                    "page": page["page"],
                    "chunk_id": chunk_id,
                },
            })
            chunk_id += 1
    return chunks


#  Embedding + ChromaDB Storage  

embedding_model = SentenceTransformer(EMBEDDING_MODEL) 
chroma_client = chromadb.PersistentClient(path=CHROMA_PERSIST_DIR)


def get_or_create_collection(domain: str) -> chromadb.Collection:
    """Get or create a ChromaDB collection for a domain."""
    collection_name = DOMAIN_COLLECTIONS.get(domain)
    if not collection_name:
        raise ValueError(f"Unknown domain: {domain}. Valid: {list(DOMAIN_COLLECTIONS.keys())}")
    return chroma_client.get_or_create_collection(name=collection_name)


def embed_and_store(chunks: list[dict], domain: str) -> int:
    """It will embed the chunks and store them in the domain's ChromaDB collection.
    Also returns the number of chunks stored."""
    collection = get_or_create_collection(domain)

    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]

    # Add domain to each chunk's metadata
    for m in metadatas:
        m["domain"] = domain

    embeddings = embedding_model.encode(texts).tolist()

    # Unique IDs: filename_chunkN
    ids = [f"{metadatas[i]['filename']}_chunk{metadatas[i]['chunk_id']}" for i in range(len(chunks))]

    collection.add(
        ids=ids,
        documents=texts,
        embeddings=embeddings,
        metadatas=metadatas,
    )

    return len(chunks)


def ingest_document(file_path: str, domain: str) -> dict:
    """Full pipeline: 
       We first parse, then chunk the parsed texts.
       After that we get the embeding and store them in Chroma DB.
       Finally returns summary."""
    filename = Path(file_path).name
    pages = parse_document(file_path)
    chunks = chunk_document(pages, filename)
    stored = embed_and_store(chunks, domain)
    return {
        "filename": filename,
        "domain": domain,
        "pages_parsed": len(pages),
        "chunks_stored": stored,
    }
