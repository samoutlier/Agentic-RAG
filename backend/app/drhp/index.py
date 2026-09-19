"""Agent 0, part 4: a search index for one document, with every chunk
tagged by the section it came from.

Each uploaded DRHP / RHP gets its own index, so a question about one IPO
never pulls text from another. The section tags let an agent search only
its part of the document, e.g. the Legal agent searching just the
"litigation" and "approvals" sections instead of all 500 pages.

Search is hybrid: embeddings find passages with the same meaning, and BM25
keyword scoring finds passages with the same words. Keywords matter in
these documents: names, defined terms ("Book Running Lead Managers") and
table rows that read nothing like a question.
"""
import json
import re
from pathlib import Path

import faiss
import numpy as np
from langchain.text_splitter import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

from app.config import IPO_CHUNK_SIZE, IPO_CHUNK_OVERLAP
from app.drhp.sections import SECTION_PREFIX, Section, normalise_title, section_key
from app.ingest import EMBEDDING_DIM, embed

splitter = RecursiveCharacterTextSplitter(
    chunk_size=IPO_CHUNK_SIZE,
    chunk_overlap=IPO_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", " ", ""],
)

# Boilerplate that no agent uses and investors rarely ask about. Leaving it
# out of the index cuts embedding, the slow part of Agent 0 on a CPU, by
# about a third. The trade-off: chat can't answer questions about these
# sections, such as the bidding procedure or the Articles of Association.
SKIPPED_SECTIONS = re.compile(
    r"^(MAIN PROVISIONS OF THE ARTICLES|DEFINITIONS AND ABBREVIATIONS|(ISSUE|OFFER) PROCEDURE"
    r"|KEY REGULATIONS AND POLICIES|OTHER REGULATORY AND STATUTORY DISCLOSURES"
    r"|STATEMENT OF (POSSIBLE )?SPECIAL TAX BENEFITS|TERMS OF THE (ISSUE|OFFER)"
    r"|CERTAIN CONVENTIONS|FORWARD-LOOKING STATEMENTS|DECLARATION"
    r"|MATERIAL CONTRACTS AND DOCUMENTS|RESTRICTIONS ON FOREIGN OWNERSHIP)"
)


def _section_of_each_page(sections: list[Section], page_count: int) -> list[Section | None]:
    """The most specific section each PDF page belongs to. Chapters (level 2)
    sit inside parts (level 1), so they're applied second and win."""
    by_page: list[Section | None] = [None] * page_count
    for level in (1, 2):
        for section in sections:
            if section.level == level:
                for index in range(section.start_index, min(section.end_index, page_count - 1) + 1):
                    by_page[index] = section
    return by_page


def _is_skipped(section: Section | None) -> bool:
    """Pages before the first section (cover, table of contents), and boilerplate."""
    if section is None:
        return True
    return bool(SKIPPED_SECTIONS.match(normalise_title(SECTION_PREFIX.sub("", section.title))))


def build_index(page_texts: list[str], sections: list[Section], folder: Path) -> tuple[int, int]:
    """Chunk the useful pages, embed the chunks, and save the index in `folder`.
    Returns (number of chunks, number of pages skipped).

    Pages are chunked separately (a chunk never spans two pages), so every
    search result can cite one exact page.
    """
    offset = sections[0].start_index - sections[0].start_page
    page_sections = _section_of_each_page(sections, len(page_texts))

    chunks = []
    skipped_pages = 0
    for index, text in enumerate(page_texts):
        section = page_sections[index]
        if _is_skipped(section):
            skipped_pages += 1
            continue
        for piece in splitter.split_text(text):
            chunks.append({
                "chunk_id": len(chunks),
                "text": piece,
                "page": index - offset,
                "section": section.key,
                "section_title": section.title,
            })

    embeddings = embed([c["text"] for c in chunks])

    # With unit-length vectors, the inner product IS the cosine similarity,
    # so search scores come out directly as similarities between 0 and 1.
    index = faiss.IndexFlatIP(EMBEDDING_DIM)
    index.add(embeddings)

    folder.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(folder / "index.faiss"))
    (folder / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    return len(chunks), skipped_pages


# Common words that would otherwise make every chunk look like a keyword match
STOPWORDS = set(
    "a an the of and or to in on for by with from as at is are was were be been this that these "
    "those it its our we us their they which who whom what how any all such other than not no "
    "has have had will would shall may can do does".split()
)
CANDIDATES = 50  # results each method contributes before they're combined
RRF_K = 60       # the usual constant for reciprocal rank fusion


def _words(text: str) -> list[str]:
    """Lowercase words minus stopwords, with a plural "s" dropped, so a
    query about "managers" matches a document that says "Manager"."""
    words = []
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        words.append(word)
    return words


class DocumentIndex:
    """A document's search index, loaded from disk. Load it once per analysis
    and reuse it for every search."""

    def __init__(self, folder: Path):
        self.index = faiss.read_index(str(folder / "index.faiss"))
        self.chunks = json.loads((folder / "chunks.json").read_text(encoding="utf-8"))
        for chunk in self.chunks:
            # Re-derived from the title, so sections added to SECTION_PATTERNS
            # later become searchable without re-embedding the document
            chunk["section"] = section_key(chunk["section_title"])
        # Keyword scoring needs the word counts of every chunk; building
        # them takes about a second, so they aren't saved to disk
        self.bm25 = BM25Okapi([_words(c["text"]) for c in self.chunks])

    def _allowed(self, sections: list[str] | None) -> np.ndarray | None:
        if not sections:
            return None
        return np.array([c["chunk_id"] for c in self.chunks if c["section"] in sections], dtype=np.int64)

    def _dense(self, query: str, allowed: np.ndarray | None) -> list[tuple[int, float]]:
        """(chunk id, cosine similarity) for the passages closest in meaning."""
        vector = embed([query])
        params, k = None, CANDIDATES
        if allowed is not None:
            # FAISS skips every chunk outside these ids while searching
            params = faiss.SearchParameters(sel=faiss.IDSelectorBatch(allowed))
            k = min(k, len(allowed))
        scores, ids = self.index.search(vector, k, params=params)
        return [(int(i), float(s)) for s, i in zip(scores[0], ids[0]) if i != -1]

    def _keyword(self, query: str, allowed: np.ndarray | None) -> list[int]:
        """Chunk ids ranked by BM25: rare query words that appear often in
        a short chunk score highest."""
        scores = self.bm25.get_scores(_words(query))
        ids = allowed if allowed is not None else np.arange(len(self.chunks))
        ranked = ids[np.argsort(-scores[ids])][:CANDIDATES]
        return [int(i) for i in ranked if scores[i] > 0]

    def search(self, query: str, k: int = 5, sections: list[str] | None = None) -> list[dict]:
        """The k best chunks for `query`, best first. Pass `sections` to
        search only those. Each result has "score" (the combined rank score)
        and "similarity" (cosine similarity, None if found by keywords alone).

        The two result lists are combined with reciprocal rank fusion: a
        chunk scores 1 / (60 + its rank) in each list it appears in. Ranks,
        not raw scores, are added because cosine and BM25 scores aren't on
        the same scale. A chunk near the top of both lists wins.
        """
        allowed = self._allowed(sections)
        if allowed is not None and len(allowed) == 0:
            return []
        dense = self._dense(query, allowed)
        similarity = dict(dense)
        fused: dict[int, float] = {}
        for ranking in ([i for i, _ in dense], self._keyword(query, allowed)):
            for rank, chunk_id in enumerate(ranking, 1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1 / (RRF_K + rank)
        best = sorted(fused, key=fused.get, reverse=True)[:k]
        return [
            {
                **self.chunks[i],
                "score": round(fused[i], 4),
                "similarity": round(similarity[i], 3) if i in similarity else None,
            }
            for i in best
        ]
