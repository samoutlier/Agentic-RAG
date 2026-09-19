"""Agent 0: turn an uploaded DRHP / RHP into everything the analysis agents need.

No LLM is involved: it's all parsing, so it's free and gives the same result
every time. It has two parts with very different speeds:

    parse_offer_document()   sections, risk headings, summary financials: seconds
    index_offer_document()   the search index: minutes on a CPU (embedding)

Agents 1 and 2 only need the parsed risk headings and financials, so the
pipeline can build the index in the background while they run.

Output is saved under ipo_data/<document id>/:

    parsed.json                sections, risk headings, summary financials
    index.faiss + chunks.json  the document's search index
"""
import hashlib
import json
import re
import time
from dataclasses import asdict
from pathlib import Path

from app.config import IPO_DATA_DIR
from app.drhp.financials import extract_summary_financials
from app.drhp.index import DocumentIndex, build_index
from app.drhp.risks import extract_risk_headings, missing_numbers
from app.drhp.sections import (
    OfferDocumentError,
    Section,
    find_sections,
    read_page_texts,
    sections_by_key,
)

# Sections the analysis can't do without. A document missing any of these
# isn't a DRHP / RHP (or couldn't be read), so it's rejected up front.
REQUIRED_SECTIONS = [
    "risk_factors", "summary_financials", "objects",
    "business", "promoters", "litigation",
]


def document_id(file_path: str) -> str:
    """A stable id from the file's name and contents. Re-uploading the same
    file gives the same id, so its saved analysis can be reused."""
    digest = hashlib.sha256(Path(file_path).read_bytes()).hexdigest()[:10]
    stem = re.sub(r"[^a-z0-9]+", "-", Path(file_path).stem.lower()).strip("-")[:40]
    return f"{stem}-{digest}"


def document_folder(doc_id: str) -> Path:
    return Path(IPO_DATA_DIR) / doc_id


def _existing_index(doc_id: str) -> dict | None:
    """The index record from an earlier run on this same file, if its index
    is still on disk. The id comes from the file's contents, so that index
    matches this file and needn't be built again."""
    folder = document_folder(doc_id)
    if (folder / "index.faiss").exists() and (folder / "parsed.json").exists():
        return load_parsed(doc_id).get("index")
    return None


def _save_parsed(parsed: dict) -> None:
    folder = document_folder(parsed["document_id"])
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "parsed.json").write_text(
        json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def parse_offer_document(file_path: str, build_search_index: bool = True) -> dict:
    """Run Agent 0 on a DRHP / RHP and save the results.

    Pass build_search_index=False to skip the slow part, then call
    index_offer_document() separately (e.g. in the background).
    """
    started = time.time()
    page_texts = read_page_texts(file_path)
    sections = find_sections(page_texts)
    keyed = sections_by_key(sections)

    missing = [key for key in REQUIRED_SECTIONS if key not in keyed]
    if missing:
        raise OfferDocumentError(
            f"Couldn't find these sections: {', '.join(missing)}. Is this a DRHP or RHP?"
        )

    risks = extract_risk_headings(file_path, keyed["risk_factors"])
    financials = extract_summary_financials(file_path, keyed["summary_financials"])

    doc_id = document_id(file_path)
    parsed = {
        "document_id": doc_id,
        "filename": Path(file_path).name,
        "page_count": len(page_texts),
        "sections": [asdict(s) for s in sections],
        "risks": [asdict(r) for r in risks],
        "missing_risk_numbers": missing_numbers(risks),
        "financials": asdict(financials),
        "parse_seconds": round(time.time() - started, 1),
        # Kept from an earlier run on this file, else filled in by index_offer_document()
        "index": _existing_index(doc_id),
    }
    _save_parsed(parsed)

    if build_search_index:
        parsed = index_offer_document(file_path, parsed["document_id"], page_texts, sections)
    return parsed


def index_offer_document(
    file_path: str,
    doc_id: str,
    page_texts: list[str] | None = None,
    sections: list[Section] | None = None,
) -> dict:
    """Build the document's search index and record it in parsed.json.
    Page texts and sections are re-read from the file if not passed in."""
    if page_texts is None or sections is None:
        page_texts = read_page_texts(file_path)
        sections = find_sections(page_texts)

    started = time.time()
    chunk_count, skipped_pages = build_index(page_texts, sections, document_folder(doc_id))

    parsed = load_parsed(doc_id)
    parsed["index"] = {
        "chunks": chunk_count,
        "skipped_pages": skipped_pages,
        "seconds": round(time.time() - started, 1),
    }
    _save_parsed(parsed)
    return parsed


def load_parsed(doc_id: str) -> dict:
    """The saved Agent 0 output for a document."""
    return json.loads((document_folder(doc_id) / "parsed.json").read_text(encoding="utf-8"))


def load_index(doc_id: str) -> DocumentIndex:
    return DocumentIndex(document_folder(doc_id))
