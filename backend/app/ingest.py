import json
import faiss
import numpy as np
import fitz
from docx import Document
from pathlib import Path
from sentence_transformers import SentenceTransformer
from langchain.text_splitter import RecursiveCharacterTextSplitter
from app.config import (
    CHUNK_SIZE, CHUNK_OVERLAP, ALLOWED_EXTENSIONS,
    EMBEDDING_MODEL, FAISS_INDEX_DIR, DOMAIN_COLLECTIONS,
)
from app.domain_router import detect_domain


# ── Document Parsing ──


def extract_tables_from_page(page: fitz.Page) -> str:
    """Extract tables from a PDF page as formatted text."""
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
    """Extract text and tables per page."""
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
    """Extract text and tables from a DOCX file."""
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
    """Read a plain text file."""
    text = Path(file_path).read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [{"text": text, "page": 1}]


def parse_document(file_path: str) -> list[dict]:
    """Route to the correct parser based on file extension."""
    ext = Path(file_path).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {ext}. Allowed: {ALLOWED_EXTENSIONS}")

    parser = {".pdf": parse_pdf, ".docx": parse_docx, ".txt": parse_txt}
    return parser[ext](file_path)


# ── Chunking ──


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


# ── Embedding Model ──
# Loaded once at startup (~130MB download on first run).
# All other modules import this same instance.

embedding_model = SentenceTransformer(EMBEDDING_MODEL)
EMBEDDING_DIM = embedding_model.get_sentence_embedding_dimension()


# ── FAISS Vector Store ──
# FAISS stores vectors in an efficient index for fast similarity search.
# Unlike ChromaDB, FAISS doesn't store metadata — so we keep a parallel
# JSON file (documents.json) per domain with the text and metadata for
# each vector. The position in the JSON list matches the vector's index
# in FAISS.
#
# On disk:
#   faiss_data/
#     legal_docs/
#       index.faiss      ← the vector index
#       documents.json   ← [{text, metadata}, ...] matching each vector
#     finance_docs/
#       ...


def _get_domain_dir(domain: str) -> Path:
    """Return the directory path for a domain's FAISS index + metadata."""
    collection_name = DOMAIN_COLLECTIONS.get(domain)
    if not collection_name:
        raise ValueError(f"Unknown domain: {domain}. Valid: {list(DOMAIN_COLLECTIONS.keys())}")
    domain_dir = Path(FAISS_INDEX_DIR) / collection_name
    domain_dir.mkdir(parents=True, exist_ok=True)
    return domain_dir


def load_index(domain: str) -> tuple[faiss.Index, list[dict]]:
    """Load a domain's FAISS index + documents from disk, or create empty
    ones if nothing has been ingested yet. Returns (index, documents)."""
    domain_dir = _get_domain_dir(domain)
    index_path = domain_dir / "index.faiss"
    docs_path = domain_dir / "documents.json"

    if index_path.exists() and docs_path.exists():
        index = faiss.read_index(str(index_path))
        documents = json.loads(docs_path.read_text(encoding="utf-8"))
    else:
        # IndexFlatL2 = brute-force search using Euclidean distance.
        # Simple and exact — no training needed. Good for up to ~100K vectors.
        index = faiss.IndexFlatL2(EMBEDDING_DIM)
        documents = []

    return index, documents


def _save_index(domain: str, index: faiss.Index, documents: list[dict]):
    """Persist the FAISS index and documents list to disk."""
    domain_dir = _get_domain_dir(domain)
    faiss.write_index(index, str(domain_dir / "index.faiss"))
    (domain_dir / "documents.json").write_text(
        json.dumps(documents, ensure_ascii=False), encoding="utf-8"
    )


def _drop_filename(index: faiss.Index, documents: list[dict], filename: str):
    """Remove all chunks belonging to `filename` from the index.

    FAISS has no upsert, so re-uploading a file would otherwise append a
    duplicate copy of every chunk. We rebuild the index from the vectors we
    want to keep — `reconstruct_n` reads them back out of the flat index,
    so nothing has to be re-encoded.
    """
    keep = [i for i, doc in enumerate(documents)
            if doc["metadata"].get("filename") != filename]

    if len(keep) == len(documents):
        return index, documents  # nothing to remove

    new_index = faiss.IndexFlatL2(EMBEDDING_DIM)
    if keep:
        all_vectors = index.reconstruct_n(0, index.ntotal)
        new_index.add(np.array([all_vectors[i] for i in keep], dtype=np.float32))

    return new_index, [documents[i] for i in keep]


def embed_and_store(chunks: list[dict], domain: str) -> int:
    """Embed chunks and add them to the domain's FAISS index.
    Re-ingesting the same filename replaces its previous chunks.
    Returns the number of chunks stored."""
    if not chunks:
        return 0

    index, documents = load_index(domain)

    filename = chunks[0]["metadata"]["filename"]
    index, documents = _drop_filename(index, documents, filename)

    texts = [c["text"] for c in chunks]
    metadatas = [c["metadata"] for c in chunks]

    for m in metadatas:
        m["domain"] = domain

    # Encode all chunk texts into vectors (numpy array of shape [N, 384])
    embeddings = embedding_model.encode(texts, normalize_embeddings=True)
    embeddings = np.array(embeddings, dtype=np.float32)

    index.add(embeddings)

    # Store text + metadata in the parallel list (same order as vectors)
    for text, meta in zip(texts, metadatas):
        documents.append({"text": text, "metadata": meta})

    _save_index(domain, index, documents)
    return len(chunks)


def ingest_document(file_path: str, domain: str | None = None) -> dict:
    """Full pipeline: parse → detect domain (if not given) → chunk → embed → store.

    Domain detection happens here, after parsing, because it needs the
    document's actual text — the raw uploaded bytes of a PDF or DOCX are
    binary and carry no readable keywords.
    """
    filename = Path(file_path).name
    pages = parse_document(file_path)

    if not pages:
        raise ValueError("No readable text could be extracted from this document.")

    if not domain:
        sample_text = "\n".join(p["text"] for p in pages)[:5000]
        domain = detect_domain(sample_text)

    chunks = chunk_document(pages, filename)
    stored = embed_and_store(chunks, domain)
    return {
        "filename": filename,
        "domain": domain,
        "pages_parsed": len(pages),
        "chunks_stored": stored,
    }
