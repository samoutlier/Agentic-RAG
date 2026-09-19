"""Agent 0, part 1: find the sections of a DRHP / RHP from its table of contents.

These PDFs have no bookmarks, but every one starts with a printed table of
contents in SEBI's fixed format, for example:

    SECTION III – RISK FACTORS ................................ 34
    OBJECTS OF THE ISSUE ...................................... 129

This module turns that into a list of sections with page ranges, so each
analysis agent can read only the pages it needs instead of all 500.
"""
import re
from collections import Counter
from dataclasses import dataclass

import fitz


class OfferDocumentError(ValueError):
    """The file doesn't look like a DRHP / RHP (the API turns this into a 400)."""


@dataclass
class Section:
    title: str         # as printed in the table of contents
    key: str | None    # our name for it, if an agent uses this section
    level: int         # 1 = "SECTION III – ..." part, 2 = chapter inside a part
    start_page: int    # printed page number: what citations should show
    end_page: int
    start_index: int   # 0-based PDF page index: what PyMuPDF needs
    end_index: int
    verified: bool     # the title was found on the page it starts on


# A table-of-contents line: a title, a run of dot leaders, then a page number
TOC_ENTRY = re.compile(r"^(?P<title>.*?)\s*[.…]{4,}\s*(?P<page>\d{1,4})\s*$")

# "SECTION III – " / "SECTION IV: " prefix that starts each top-level part
SECTION_PREFIX = re.compile(r"^SECTION\s+[IVXL]+\s*[-–—:]?\s*", re.IGNORECASE)

# The sections the agents need, and how documents title them. SEBI fixes the
# structure but not the exact wording: some say "Issue" where others say "Offer".
SECTION_PATTERNS = {
    "summary": r"^SUMMARY OF (THE )?(OFFER|ISSUE) DOCUMENT|^OFFER DOCUMENT SUMMARY",
    "risk_factors": r"^RISK FACTORS",
    "summary_financials": r"^SUMMARY (OF )?FINANCIAL INFORMATION",
    "capital_structure": r"^CAPITAL STRUCTURE",
    "objects": r"^OBJECTS? OF THE (OFFER|ISSUE)",
    "basis_for_price": r"^BASIS FOR (THE )?(OFFER|ISSUE) PRICE",
    "industry": r"^INDUSTRY OVERVIEW",
    "business": r"^OUR BUSINESS",
    "management": r"^OUR MANAGEMENT",
    "promoters": r"^OUR PROMOTERS?\b",
    "restated_financials": r"^RESTATED\b.*FINANCIAL (INFORMATION|STATEMENTS)",
    "other_financial_info": r"^OTHER FINANCIAL INFORMATION",
    "mdna": r"^MANAGEMENT.S DISCUSSION AND ANALYSIS",
    "indebtedness": r"^FINANCIAL INDEBTEDNESS",
    "litigation": r"^OUTSTANDING LITIGATION",
    "approvals": r"^GOVERNMENT AND OTHER APPROVALS",
    "the_offer": r"^THE (OFFER|ISSUE)$",
    "general_information": r"^GENERAL INFORMATION",
    "related_party": r"^(SUMMARY OF )?RELATED PARTY TRANSACTIONS",
    "history": r"^HISTORY AND CERTAIN CORPORATE MATTERS",
    "group_companies": r"^(OUR )?GROUP COMPANIES",
}


def section_key(title: str) -> str | None:
    """The standard key for a section title, or None if agents don't use it."""
    name = normalise_title(SECTION_PREFIX.sub("", title))
    for key, pattern in SECTION_PATTERNS.items():
        if re.search(pattern, name):
            return key
    return None


def normalise_title(text: str) -> str:
    """Uppercase, straight quotes, single spaces: makes titles comparable."""
    text = text.replace("’", "'").replace("‘", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s+", " ", text).strip().upper()


def _looks_like_heading(line: str) -> bool:
    """TOC titles are in capitals; ordinary sentences on the same page aren't."""
    letters = [c for c in line if c.isalpha()]
    return len(letters) >= 3 and sum(c.isupper() for c in letters) / len(letters) > 0.8


def _find_toc_start(page_texts: list[str]) -> int:
    for i, text in enumerate(page_texts[:20]):
        if "TABLE OF CONTENTS" in text.upper():
            return i
    for i, text in enumerate(page_texts[:20]):
        if re.search(r"^\s*CONTENTS\s*$", text, re.MULTILINE | re.IGNORECASE):
            return i
    raise OfferDocumentError(
        "No table of contents found in the first 20 pages. "
        "This doesn't look like a DRHP or RHP."
    )


def _read_toc(page_texts: list[str]) -> list[tuple[str, int]]:
    """Return (title, printed page) for every table-of-contents entry.

    Long titles wrap onto two lines, and only the second line ends with the
    page number, so a capitalised line without a page number is kept and
    joined to the next entry.
    """
    start = _find_toc_start(page_texts)
    entries = []
    for text in page_texts[start:start + 4]:  # a TOC spans at most a few pages
        found_on_page = 0
        pending = ""
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or "CONTENTS" in line.upper():
                continue
            match = TOC_ENTRY.match(line)
            if match:
                title = f"{pending} {match['title']}".strip()
                pending = ""
                if _looks_like_heading(title):
                    entries.append((re.sub(r"\s+", " ", title), int(match["page"])))
                    found_on_page += 1
            elif _looks_like_heading(line) and len(pending) < 150:
                pending = f"{pending} {line}".strip()
            else:
                pending = ""
        if entries and found_on_page == 0:
            break  # the table of contents has ended
    if len(entries) < 5:
        raise OfferDocumentError("The table of contents couldn't be read. Is this a DRHP or RHP?")
    return entries


# Unnumbered cover pages put printed page 1 this many PDF pages in, at most
MAX_COVER_PAGES = 60

# A printed page number on its own line: "26" in most documents, "Page | 26" in some
PAGE_NUMBER_LINE = re.compile(r"^(?:page\s*[|:]?\s*)?(\d{1,4})$", re.IGNORECASE)


def _page_offset(page_texts: list[str]) -> int:
    """How far PDF page indexes are ahead of printed page numbers.

    Cover pages aren't numbered, so printed page 1 is usually a few PDF pages
    in. Each page's printed number sits alone on a line in its footer. Other
    lone numbers appear too (years like "2025", table values), so only
    numbers that could be this page's number count, and the most common
    (index - number) difference across the document wins.
    """
    differences = Counter()
    for index, text in enumerate(page_texts):
        for line in text.splitlines():
            match = PAGE_NUMBER_LINE.match(line.strip())
            if match and 0 <= index - int(match[1]) <= MAX_COVER_PAGES:
                differences[index - int(match[1])] += 1
    if not differences:
        raise OfferDocumentError("No printed page numbers found. Is this a DRHP or RHP?")
    return differences.most_common(1)[0][0]


def _locate_start(title: str, expected_index: int, page_texts: list[str]) -> tuple[int, bool]:
    """Check the title really appears where the TOC says; if not, look nearby."""
    wanted = normalise_title(SECTION_PREFIX.sub("", title))[:30]
    for shift in (0, 1, -1, 2, -2, 3, -3):
        index = expected_index + shift
        if 0 <= index < len(page_texts) and wanted in normalise_title(page_texts[index]):
            return index, True
    return expected_index, False


def find_sections(page_texts: list[str]) -> list[Section]:
    """Every section in the table of contents, with its page range."""
    entries = _read_toc(page_texts)
    offset = _page_offset(page_texts)
    last_index = len(page_texts) - 1

    starts = []
    for title, printed_page in entries:
        index, verified = _locate_start(title, printed_page + offset, page_texts)
        starts.append((title, index, verified))

    sections = []
    for i, (title, start_index, verified) in enumerate(starts):
        level = 1 if SECTION_PREFIX.match(title) else 2
        # A chapter ends where the next entry begins; a whole part ("SECTION ...")
        # ends where the next part begins.
        later = [s for s in starts[i + 1:] if level == 2 or SECTION_PREFIX.match(s[0])]
        end_index = max(start_index, later[0][1] - 1) if later else last_index

        sections.append(Section(
            title=title,
            key=section_key(title),
            level=level,
            start_page=start_index - offset,
            end_page=end_index - offset,
            start_index=start_index,
            end_index=end_index,
            verified=verified,
        ))
    return sections


def sections_by_key(sections: list[Section]) -> dict[str, Section]:
    """The sections the agents use, looked up by key (first match wins)."""
    found = {}
    for section in sections:
        if section.key and section.key not in found:
            found[section.key] = section
    return found


def section_pages(page_texts: list[str], section: Section) -> list[tuple[int, str]]:
    """(printed page number, text) for every page of a section, so anything
    built from the text can cite the page it came from."""
    offset = section.start_index - section.start_page
    return [
        (index - offset, page_texts[index])
        for index in range(section.start_index, section.end_index + 1)
    ]


def read_page_texts(file_path: str) -> list[str]:
    """Plain text of every page. Slow for a 500-page PDF (~20-30 s), so it's
    done once and the result shared by every part of Agent 0."""
    with fitz.open(file_path) as doc:
        return [page.get_text() for page in doc]
