"""Agent 0, part 2: the list of risk factors, taken from their headings.

Every risk in the Risk Factors section starts with a numbered heading in bold
that sums it up in a sentence or two, for example:

    2. Our revenue ... from government entities ... may adversely affect our business.

Agent 1 classifies these headings instead of reading all 30-55 pages of the
section, which keeps its prompt to a few thousand tokens.
"""
import re
from dataclasses import dataclass

import fitz

from app.drhp.sections import Section


@dataclass
class RiskHeading:
    number: int
    text: str
    page: int          # printed page number, for citations
    group: str | None  # e.g. "Internal Risk Factors", when the document groups risks


# A heading starts with its number: "12. Our revenue ..." or, in some
# documents, just "12." on its own line with the text on the next lines.
# After the number comes a space, a capital letter (possibly after an opening
# quote, as in '16.“The use of ...'), or the end of the line. The number and
# the text can be separate pieces joined without a space. Requiring one of
# these excludes decimals like "1.5 million".
HEADING_START = re.compile(r"^(\d{1,3})[.)](?:\s+|(?=[“\"‘']?[A-Z])|$)(.*)$")

# Headings are numbered 1, 2, 3, ... A bold numbered line that jumps further
# than this ahead is something else (e.g. a numbered list inside a table).
MAX_NUMBER_GAP = 3


def _is_bold(span: dict) -> bool:
    return bool(span["flags"] & 16) or "bold" in span["font"].lower()


def _lines(page: fitz.Page):
    """Yield (text, is_bold) for each line on a page, in reading order."""
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["text"].strip()]
            if not spans:
                continue
            text = re.sub(r"\s+", " ", "".join(s["text"] for s in spans)).strip()
            total = sum(len(s["text"].strip()) for s in spans)
            bold = sum(len(s["text"].strip()) for s in spans if _is_bold(s))
            yield text, bold / total >= 0.8


def _is_group_title(text: str) -> bool:
    """Short bold titles like "INTERNAL RISK FACTORS" that group the risks.
    A title starts with a capital and has no full stop at the end, which
    rules out bold fragments of sentences such as "inherent risks."."""
    upper = text.upper()
    return (
        "RISK" in upper
        and len(text) < 100
        and text[0].isupper()
        and not text.rstrip().endswith(".")
        and not upper.startswith("SECTION")
    )


def extract_risk_headings(file_path: str, section: Section) -> list[RiskHeading]:
    """Every numbered risk heading in the Risk Factors section, in order."""
    offset = section.start_index - section.start_page
    risks: list[RiskHeading] = []
    current: RiskHeading | None = None  # the heading being read, while its lines are bold
    group: str | None = None
    last_number = 0

    with fitz.open(file_path) as doc:
        for index in range(section.start_index, section.end_index + 1):
            for text, bold in _lines(doc[index]):
                match = HEADING_START.match(text) if bold else None
                if match and last_number < int(match[1]) <= last_number + MAX_NUMBER_GAP:
                    current = RiskHeading(
                        number=int(match[1]),
                        text=match[2] or "",
                        page=index - offset,
                        group=group,
                    )
                    risks.append(current)
                    last_number = current.number
                elif current and bold:
                    # The heading continues on the next line
                    current.text = f"{current.text} {text}".strip()
                else:
                    # A normal (non-bold) line: we're in the risk's body, not its heading
                    current = None
                    if bold and _is_group_title(text):
                        group = text.rstrip(":").strip()
    return risks


def missing_numbers(risks: list[RiskHeading]) -> list[int]:
    """Risk numbers skipped in the sequence: each one is a heading we failed to read."""
    found = {risk.number for risk in risks}
    return [n for n in range(1, max(found, default=0) + 1) if n not in found]
