"""The excerpts an agent reads, each labelled with its page, and the checks
on what the agent says about them. Used by Agents 3, 4 and 5.

An agent collects excerpts in order of importance, from two sources:
  - the opening pages of a short section, read straight from the PDF
    (e.g. the "The Offer" table, the start of "Objects of the Offer")
  - hybrid-search results, for facts that could be anywhere in a long
    section (e.g. whether any promoter shares are pledged)
Then render() keeps as many as fit the token budget and shows them in page
order, each starting with "[p.92]" so the model can cite it.
"""
import re

import fitz
from pydantic import BaseModel

from app.agents.checks import number_in, unsupported_figures
from app.agents.structured import estimate_tokens
from app.drhp.index import DocumentIndex
from app.drhp.sections import section_key

MAX_PAGE_CHARS = 4000  # one dense page is plenty; the rest is often boilerplate


class Claim(BaseModel):
    """A statement and the pages that support it."""
    text: str
    pages: list[int] = []


def _clean(text: str) -> str:
    """Collapse the line breaks and spacing of PDF tables: fewer tokens."""
    return re.sub(r"\s+", " ", text).strip()


class Evidence:
    def __init__(self, file_path: str, parsed: dict, index: DocumentIndex | None = None):
        self.file_path = file_path
        self.index = index  # needed only for add_search()
        # Keys re-derived from titles, so documents parsed before a key was
        # added still have it. The first section with a key wins.
        self.sections: dict[str, dict] = {}
        for section in parsed["sections"]:
            key = section_key(section["title"])
            if key and key not in self.sections:
                self.sections[key] = section
        self.excerpts: list[tuple[int, str]] = []  # (page, text), most important first
        self._seen: set[tuple[str, int]] = set()
        self.pages: set[int] = set()  # pages actually shown to the model, set by render()
        self.source = ""              # the text actually shown, set by render()

    def add_pages(self, key: str, count: int = 1) -> None:
        """The first `count` pages of a section, read from the PDF."""
        section = self.sections.get(key)
        if not section:
            return
        offset = section["start_index"] - section["start_page"]
        last = min(section["start_index"] + count - 1, section["end_index"])
        with fitz.open(self.file_path) as pdf:
            for index in range(section["start_index"], last + 1):
                page = index - offset
                if ("page", page) not in self._seen:
                    self._seen.add(("page", page))
                    self.excerpts.append((page, _clean(pdf[index].get_text())[:MAX_PAGE_CHARS]))

    def section_texts(self, key: str) -> list[tuple[int, str]]:
        """(page, text) for every page of a section, read from the PDF."""
        section = self.sections.get(key)
        if not section:
            return []
        offset = section["start_index"] - section["start_page"]
        with fitz.open(self.file_path) as pdf:
            return [
                (index - offset, _clean(pdf[index].get_text()))
                for index in range(section["start_index"], section["end_index"] + 1)
            ]

    def add_text(self, page: int, text: str) -> None:
        """An excerpt the agent picked itself, e.g. one page of a batch."""
        if ("page", page) not in self._seen:
            self._seen.add(("page", page))
            self.excerpts.append((page, text))

    def add_search(self, query: str, sections: list[str], k: int = 2) -> None:
        """The top k search results within `sections` (those the document
        has), skipping text already included."""
        sections = [s for s in sections if s in self.sections]
        if not sections:
            return
        for hit in self.index.search(query, k=k, sections=sections):
            if ("page", hit["page"]) in self._seen or ("chunk", hit["chunk_id"]) in self._seen:
                continue
            self._seen.add(("chunk", hit["chunk_id"]))
            self.excerpts.append((hit["page"], _clean(hit["text"])))

    def scan(self, key: str, pattern: re.Pattern) -> dict | None:
        """The first match of `pattern` in a section's full page text, with
        its page. For standard sentences that search chunks may cut in two."""
        section = self.sections.get(key)
        if not section:
            return None
        offset = section["start_index"] - section["start_page"]
        with fitz.open(self.file_path) as pdf:
            for index in range(section["start_index"], section["end_index"] + 1):
                match = pattern.search(_clean(pdf[index].get_text()))
                if match:
                    return {"text": match.group(0), "pages": [index - offset]}
        return None

    def render(self, max_tokens: int) -> str:
        """The excerpts that fit in max_tokens, most important first, shown
        in page order. Records which pages and text the model will see."""
        chosen, used = [], 0
        for page, text in self.excerpts:
            cost = estimate_tokens(text) + 6
            if used + cost <= max_tokens:  # one that doesn't fit is skipped; a smaller one may
                chosen.append((page, text))
                used += cost
        chosen.sort(key=lambda excerpt: excerpt[0])
        self.pages = {page for page, _ in chosen}
        self.source = "\n\n".join(f"[p.{page}] {text}" for page, text in chosen)
        return self.source

    # ── Checks on the model's answer ──

    def claim(self, claim: Claim | None, label: str, warnings: list[str]) -> dict | None:
        """A claim with citations of pages the model wasn't shown removed,
        and a warning if it has figures that aren't in the excerpts."""
        if claim is None:
            return None
        pages = sorted({p for p in claim.pages if p in self.pages})
        if not pages:
            warnings.append(f"{label}: no citation of a page the model was shown")
        elif len(pages) < len(set(claim.pages)):
            warnings.append(f"{label}: dropped citations of pages the model wasn't shown")
        unsupported = unsupported_figures(claim.text, self.source)
        if unsupported:
            warnings.append(f"{label}: figures not found in the excerpts: {', '.join(unsupported)}")
        return {"text": claim.text.strip(), "pages": pages}

    def cited(self, pages: list[int]) -> list[int]:
        return sorted({p for p in pages if p in self.pages})

    def number(self, value: float | None, label: str, warnings: list[str]) -> float | None:
        """An extracted number, or None if it isn't in the excerpts."""
        if value is None or number_in(value, self.source):
            return value
        warnings.append(f"{label} ({value}) isn't in the excerpts, so it was left out")
        return None
