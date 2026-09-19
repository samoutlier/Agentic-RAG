"""Agent 0, part 3: the Summary of Financial Information, as numbers.

Agent 2 computes its ratios (growth, margins, debt-to-equity...) in Python
from these numbers, rather than asking the LLM to do arithmetic.

What real documents look like, and how this handles it:
  - Each statement (balance sheet, profit and loss, cash flow) is a table.
  - Values don't always sit in the same column as their period header
    (merged cells shift them), but they always appear in the same
    left-to-right order. So periods are read from the header text in order,
    and each row's numbers are matched to them in order.
  - Units differ (₹ million, lakh, crore): everything is converted to ₹ million.
  - Most documents include a part-year period (e.g. six months to September),
    which is marked so it's kept out of annual ratios.
"""
import re
from dataclasses import dataclass, field

import fitz

from app.drhp.sections import Section

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]
MONTHS = "|".join(MONTH_NAMES)
MONTH_NUMBER = {name.lower(): number for number, name in enumerate(MONTH_NAMES, start=1)}

# A period in a column header, in any of the forms documents use:
# "March 31, 2024", "30th June, 2026" or "Fiscal 2025"
PERIOD = re.compile(
    rf"(?P<month>{MONTHS})\s+(?P<day>\d{{1,2}}),?\s+(?P<year>\d{{4}})"
    rf"|(?P<day2>\d{{1,2}})(?:st|nd|rd|th)?\s+(?P<month2>{MONTHS}),?\s+(?P<year2>\d{{4}})"
    rf"|Fiscal\s+(?P<fy>\d{{4}})",
    re.IGNORECASE,
)

# How each statement is titled on its page
STATEMENTS = {
    "balance_sheet": r"ASSETS AND LIABILITIES|BALANCE SHEET",
    "profit_and_loss": r"PROFIT AND LOSS|PROFIT & LOSS",
    "cash_flow": r"CASH FLOW",
}

# Our name for each line item -> how documents label it (after cleaning)
ITEMS = {
    "profit_and_loss": {
        "revenue_from_operations": r"^revenue from operations",
        "other_income": r"^other income",
        "total_income": r"^total (income|revenue)",
        "finance_costs": r"^finance costs?",
        "depreciation": r"^depreciation",
        "total_expenses": r"^total expenses",
        "profit_before_tax": r"^(?!.*exceptional).*before tax",
        "profit_for_period": r"^(net )?profit.{0,12}for the (year|period)(?!.*(continuing|discontinued|attributable))",
        "eps_basic": r"^basic",
    },
    "balance_sheet": {
        "total_assets": r"^total assets",
        "total_current_assets": r"^total current assets",
        "total_current_liabilities": r"^total current liabilities",
        "total_equity": r"^total equity(?! and)",
        "cash_and_equivalents": r"^cash (and|&) cash equivalents",
        "trade_receivables": r"^trade receivables",
        "inventories": r"^inventories",
        "borrowings": r"^(non-current |current )?borrowings",
    },
    "cash_flow": {
        "operating_cash_flow": r"^net cash.*operating",
        "investing_cash_flow": r"^net cash.*investing",
        "financing_cash_flow": r"^net cash.*financing",
        # "Purchase of", "(Purchase) of", "Investments in" or "Payment for"
        # property, plant and equipment
        "capex": r"^\(?(purchase|acquisition|investments?|payments?)\)?\s*(of|in|for)\s+property,? plant",
    },
}

# Borrowings appear twice (non-current and current liabilities): add them up
SUMMED_ITEMS = {"borrowings"}

# Per-share figures are in rupees, not in the statement's unit
PER_SHARE_ITEMS = {"eps_basic"}

# Multiply by this to convert a reported unit to ₹ million
TO_MILLION = {"million": 1.0, "lakh": 0.1, "crore": 10.0}

NIL_VALUES = {"-", "–", "—", "nil"}

# A number with valid digit grouping: 1234.5, 1,234.56 or Indian-style 1,23,456.
# The strict grouping matters: header fragments like "31, 2026" must not
# be mistaken for the number 312026.
NUMBER = re.compile(r"^\(?-?(\d{1,3}(,\d{2,3})+|\d+)(\.\d+)?\)?$")


@dataclass
class SummaryFinancials:
    reported_unit: str                   # "million", "lakh" or "crore", as printed
    periods: list[dict]                  # newest first: [{"label": "FY2024", "full_year": True}, ...]
    items: dict[str, dict[str, float]]   # item -> period label -> value in ₹ million
    pages: dict[str, int]                # statement -> printed page it starts on
    warnings: list[str] = field(default_factory=list)


def _parse_value(cell: str) -> float | None:
    """'1,234.56' -> 1234.56, '(229.22)' -> -229.22, '-' -> 0.0, text -> None."""
    text = cell.replace("₹", "").replace(" ", "").rstrip("*#^").strip()
    if text.lower() in NIL_VALUES:
        return 0.0
    if "%" in text or not NUMBER.match(text):
        return None
    negative = text.startswith("(") or text.startswith("-")
    value = float(text.strip("()-").replace(",", ""))
    return -value if negative else value


def _looks_like_year(value: float) -> bool:
    return value.is_integer() and 1990 <= value <= 2100


def _clean_label(text: str) -> str:
    """'(a) Trade Receivables' / '- Cash & Cash Equivalents' -> 'trade receivables' / ..."""
    text = re.sub(r"\s+", " ", text).strip().lower()
    return re.sub(r"^((\(?[a-z0-9]{1,4}[.)])\s*|[-•]\s*)+", "", text)


def _period(match: re.Match) -> tuple[str, bool, tuple[int, int]]:
    """(label, is a full year, (year, month) for sorting) for a matched period.
    Indian fiscal years end on March 31, so 'March 31, 2024' is FY2024."""
    if match["fy"]:
        return f"FY{match['fy']}", True, (int(match["fy"]), 3)
    month = (match["month"] or match["month2"]).capitalize()
    day = match["day"] or match["day2"]
    year = int(match["year"] or match["year2"])
    if month == "March" and day == "31":
        return f"FY{year}", True, (year, 3)
    return f"{month[:3]} {day}, {year}", False, (year, MONTH_NUMBER[month.lower()])


def _read_table(rows: list[list]) -> tuple[list[tuple], list[tuple[str, list[float], str]]]:
    """Split a table into its periods (from the header rows) and
    (label, values, parent) rows, where parent is the heading row above,
    e.g. "Trade receivables" above "Billed" and "Unbilled"."""
    cells = [[(c or "").replace("\n", " ").strip() for c in row] for row in rows]

    # Header rows come before the first row holding real numbers (years don't count)
    header_end = 0
    for i, row in enumerate(cells):
        values = [v for v in map(_parse_value, row) if v is not None]
        if len(values) >= 2 and not all(_looks_like_year(v) for v in values):
            header_end = i
            break

    # Join each column's header cells top to bottom, then read left to right
    columns = [" ".join(row[c] for row in cells[:header_end]) for c in range(len(cells[0]))]
    periods = [_period(m) for m in PERIOD.finditer(" ".join(columns))]

    entries: list[tuple[str, list[float], str]] = []
    pending = ""  # a label printed on its own line, before the row with its numbers
    parent = ""   # the most recent heading row (a label with no numbers)
    for row in cells[header_end:]:
        values = [v for v in map(_parse_value, row) if v is not None]
        label = next((c for c in row if c and _parse_value(c) is None), "")
        if values:
            if pending and (not label or label[0].islower()):
                label = f"{pending} {label}".strip()
            entries.append((label, values, parent))
            pending = ""
        elif label:
            if entries and (label[0].islower() or label.startswith(")")):
                # The previous row's label wrapped onto this line
                last_label, last_values, last_parent = entries[-1]
                entries[-1] = (f"{last_label} {label}", last_values, last_parent)
            else:
                pending = label
                parent = label
    return periods, entries


def _match_item(statement: str, label: str, parent: str) -> str | None:
    """Which line item a row is, if any. The row's own label is tried first;
    only if nothing matches is it combined with its heading row, so a
    sub-row like "Billed" under "Trade receivables" is still recognised."""
    candidates = [_clean_label(label)]
    if parent:
        candidates.append(_clean_label(f"{parent} {label}"))
    for candidate in candidates:
        for item, pattern in ITEMS[statement].items():
            if re.search(pattern, candidate):
                return item
    return None


def _detect_unit(texts: list[str]) -> str:
    joined = " ".join(texts).lower()
    for unit in ("million", "crore", "lakh"):
        if re.search(rf"in\s+{unit}", joined):
            return unit
    return "million"


def extract_summary_financials(file_path: str, section: Section) -> SummaryFinancials:
    """Key line items from the Summary of Financial Information section."""
    offset = section.start_index - section.start_page
    items: dict[str, dict[str, float]] = {}
    periods: dict[str, tuple[bool, tuple[int, int]]] = {}  # label -> (full year, sort key)
    pages: dict[str, int] = {}
    warnings: list[str] = []
    statement = None

    with fitz.open(file_path) as doc:
        texts = [doc[i].get_text() for i in range(section.start_index, section.end_index + 1)]
        unit = _detect_unit(texts)
        scale = TO_MILLION[unit]

        for index, text in zip(range(section.start_index, section.end_index + 1), texts):
            # A statement's title is at the top of its first page; a page
            # without one continues the previous statement.
            for name, pattern in STATEMENTS.items():
                if re.search(pattern, text[:600], re.IGNORECASE):
                    statement = name
                    pages.setdefault(name, index - offset)
                    break
            if statement is None:
                continue

            for table in doc[index].find_tables().tables:
                table_periods, entries = _read_table(table.extract())
                if not table_periods:
                    continue
                for label, full_year, sort_key in table_periods:
                    periods.setdefault(label, (full_year, sort_key))
                labels = [label for label, _, _ in table_periods]

                for label, values, parent in entries:
                    if len(values) < len(labels):
                        continue  # a heading row without a value per period
                    values = values[-len(labels):]  # skip any leading note-number column
                    item = _match_item(statement, label, parent)
                    if item is None:
                        continue
                    factor = 1.0 if item in PER_SHARE_ITEMS else scale
                    converted = {p: round(v * factor, 2) for p, v in zip(labels, values)}
                    if item in items and item in SUMMED_ITEMS:
                        for p, v in converted.items():
                            items[item][p] = round(items[item].get(p, 0.0) + v, 2)
                    elif item not in items:
                        items[item] = converted

    for item_group in ITEMS.values():
        for item in item_group:
            if item not in items:
                warnings.append(f"'{item}' not found")

    # Cross-check: if the columns were misread, this identity breaks
    for period, total in items.get("total_income", {}).items():
        revenue = items.get("revenue_from_operations", {}).get(period)
        other = items.get("other_income", {}).get(period)
        if revenue is not None and other is not None and total:
            if abs(total - (revenue + other)) / abs(total) > 0.01:
                warnings.append(f"Total income for {period} doesn't equal revenue + other income")

    newest_first = sorted(periods.items(), key=lambda p: p[1][1], reverse=True)
    return SummaryFinancials(
        reported_unit=unit,
        periods=[{"label": label, "full_year": full_year} for label, (full_year, _) in newest_first],
        items=items,
        pages=pages,
        warnings=warnings,
    )
