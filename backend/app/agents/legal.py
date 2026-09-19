"""Agent 5: Legal & Approvals. Outstanding cases against the company, its
promoters and directors, and the approvals it still lacks.

The litigation chapter (6–10 pages) is too long for one call, so it's read
in batches of whole pages. For each batch the LLM lists every case as one
flat record (flat lists are what small models get right). Python then
converts amounts to ₹ million, checks each against the page text, removes
cases seen twice across a page break, and adds everything up.

It reads the PDF directly, not the search index, so it can run while the
index is still being built.
"""
import re
from typing import Literal

from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.checks import number_in
from app.agents.evidence import Evidence
from app.agents.state import AnalysisState
from app.agents.structured import estimate_tokens
from app.config import LEGAL_AGENT_MODEL

Party = Literal["company", "subsidiary", "promoter", "director", "group_company", "key_management"]
CaseType = Literal["criminal", "regulatory", "sebi_disciplinary", "tax", "civil"]
AmountUnit = Literal["rupees", "thousand", "lakh", "million", "crore"]
TO_MILLION = {"rupees": 1e-6, "thousand": 1e-3, "lakh": 0.1, "million": 1.0, "crore": 10.0}
# The parties whose cases reflect on the business being bought
CORE_PARTIES = {"company", "subsidiary", "promoter", "director"}


class Case(BaseModel):
    heading: str = ""
    party: Party
    against_party: bool
    type: CaseType
    total_row: bool = False
    count: int = 1
    amount: float | None = None
    unit: AmountUnit | None = None
    summary: str
    page: int


class CaseBatch(BaseModel):
    cases: list[Case] = []


class Approvals(BaseModel):
    all_material_obtained: bool | None = None
    pending: list[str] = []
    not_applied: list[str] = []
    pages: list[int] = []


CASES_PROMPT = """You are extracting outstanding legal proceedings from the "Outstanding Litigation" chapter of an Indian IPO document. Each page starts with its page number, like [p.436].

List every proceeding described on these pages, and every table row that totals several proceedings (such as tax cases). Skip statements that there are none, and skip the materiality policy. For each:
- heading: the headings above it, from the main one down, joined with " > " and copied exactly (for example "Litigation involving our Promoters > B. Litigation filed by our Promoter > 1. Criminal proceedings")
- party: whose proceeding it is: company, subsidiary, promoter, director, group_company or key_management
- against_party: true if it is against that party, false if that party filed it
- type: criminal; regulatory (action, notice or penalty by a regulator or statutory authority); sebi_disciplinary (action by SEBI or a stock exchange against promoters); tax (direct or indirect tax claims); civil (any other material case or arbitration)
- total_row: true for a table row that totals several proceedings, false for a single case
- count: 1 for a single case, or the number of cases a total row covers
- amount and unit: the amount involved exactly as printed, and its unit (rupees, thousand, lakh, million or crore); if a case gives several amounts and no total, the largest one; null if none is stated
- summary: what it is about, in at most 20 words
- page: the page where it starts

Pages:
{excerpts}"""

APPROVALS_PROMPT = """You are reading the "Government and Other Approvals" chapter of an Indian IPO document. Each page starts with its page number, like [p.319].

Rules:
- Use only these pages. Don't list approvals the company already holds.

Return:
- all_material_obtained: true if the chapter says the company holds all material approvals (apart from any it lists as pending), false if it says some are missing, null if it doesn't say
- pending: approvals or renewals applied for but not yet received, each in a few words (empty if the chapter says "Nil" or lists none)
- not_applied: approvals required but not yet applied for (empty if none)
- pages: the pages you used

Pages:
{excerpts}"""

# Pages per litigation call: with the instructions and a reply of up to
# ~20 cases, each call stays around 6,000 tokens
BATCH_TOKENS = 3600
CASES_OUTPUT_TOKENS = 1500
APPROVALS_TOKENS = 3600
APPROVALS_OUTPUT_TOKENS = 800
PENDING_WORDING = re.compile(r"applied for|not yet (?:been )?received|yet to (?:be )?(?:apply|obtain)|expired", re.IGNORECASE)


def _page_batches(pages: list[tuple[int, str]]) -> list[list[tuple[int, str]]]:
    """Consecutive pages, as many per batch as fit in BATCH_TOKENS."""
    batches, current, used = [], [], 0
    for page, text in pages:
        cost = estimate_tokens(text)
        if current and used + cost > BATCH_TOKENS:
            batches.append(current)
            current, used = [], 0
        current.append((page, text))
        used += cost
    return batches + [current] if current else batches


# Proceedings brought by an authority are always against the party, even
# when the party has appealed (a test model filed tax demands under "by")
ALWAYS_AGAINST = {"tax", "regulatory", "sebi_disciplinary"}
DIRECTION = re.compile(r"\bagainst\b|\bby\b", re.IGNORECASE)
# Checked in this order: "Directors (except the Promoters)" is about directors
HEADING_PARTIES = [
    ("key_management", r"key managerial|senior management"),
    ("subsidiary", r"subsidiar"),
    ("group_company", r"group compan"),
    ("director", r"director"),
    ("promoter", r"promoter"),
    ("company", r"\bcompany\b"),
]


def _against(case: Case) -> bool:
    """Whether the case is against the party. The chapter's own headings
    ("Litigation filed by our Promoter", "... against our Company") are more
    reliable than the model's judgement: a test model read a complaint our
    promoter filed against "Ramprastha Promoters" as a case against him."""
    if case.type in ALWAYS_AGAINST:
        return True
    words = DIRECTION.findall(case.heading)
    if words:
        return words[-1].lower() == "against"  # the nearest heading decides
    return case.against_party


def _party(case: Case) -> str:
    """The party named by the nearest heading that names exactly one."""
    for level in reversed(case.heading.split(">")):
        named = [party for party, pattern in HEADING_PARTIES if re.search(pattern, level, re.IGNORECASE)]
        if named:
            return named[0] if len(named) == 1 or named[0] == "director" else case.party
    return case.party


def _case_record(case: Case, evidence: Evidence, warnings: list[str]) -> dict:
    amount = case.amount
    if amount is not None and not number_in(amount, evidence.source):
        warnings.append(f"Amount {amount} for '{case.summary[:40]}' isn't on its pages, so it was left out")
        amount = None
    if amount is not None and case.unit is None:
        # Guessing the unit could be off by a factor of a million
        warnings.append(f"Amount {amount} for '{case.summary[:40]}' has no unit, so it was left out")
        amount = None
    return {
        "heading": case.heading.strip(),
        "party": _party(case),
        "against_party": _against(case),
        "type": case.type,
        "total_row": case.total_row,
        "count": max(case.count, 1),
        "amount_million": round(amount * TO_MILLION[case.unit], 3) if amount is not None else None,
        "summary": case.summary.strip(),
        "page": case.page if case.page in evidence.pages else min(evidence.pages),
    }


def _dedupe(cases: list[dict]) -> list[dict]:
    """A case that starts at the bottom of one batch's last page can be
    listed again by the next batch: keep the first of each."""
    seen, unique = set(), []
    for case in cases:
        detail = case["amount_million"] if case["amount_million"] is not None else case["summary"][:30].lower()
        key = (case["party"], case["against_party"], case["type"], detail)
        if key not in seen:
            seen.add(key)
            unique.append(case)
    return unique


def _net_worth(parsed: dict) -> float | None:
    """Total equity at the latest balance-sheet date, in ₹ million."""
    financials = parsed["financials"]
    if not financials["periods"]:
        return None
    return financials["items"].get("total_equity", {}).get(financials["periods"][0]["label"])


def _mark_totals(cases: list[dict]) -> None:
    """Where a table row totals a party's cases of one type (usually tax),
    the individual cases of that party and type described elsewhere are
    part of that total: mark them so they aren't added twice."""
    totalled = {(c["party"], c["type"]) for c in cases if c["total_row"]}
    for case in cases:
        case["in_total_row"] = not case["total_row"] and (case["party"], case["type"]) in totalled


def _summarise(cases: list[dict], net_worth: float | None) -> dict:
    """Counts and amounts of cases against the company, its subsidiaries,
    promoters and directors, by type."""
    against = [c for c in cases if c["against_party"] and c["party"] in CORE_PARTIES and not c["in_total_row"]]
    by_type = {}
    for case_type in ("criminal", "regulatory", "sebi_disciplinary", "tax", "civil"):
        of_type = [c for c in against if c["type"] == case_type]
        by_type[case_type] = {
            "count": sum(c["count"] for c in of_type),
            "amount_million": round(sum(c["amount_million"] or 0 for c in of_type), 2),
        }
    total = round(sum(c["amount_million"] or 0 for c in against), 2)
    return {
        "against_by_type": by_type,
        "total_amount_against_million": total,
        "net_worth_million": net_worth,
        "amount_pct_of_net_worth": round(total / net_worth * 100, 1) if net_worth and net_worth > 0 else None,
        "filed_by_parties": sum(c["count"] for c in cases if not c["against_party"] and not c["in_total_row"]),
    }


def _legal_flags(summary: dict, approvals: dict | None) -> list[dict]:
    flags = []

    def flag(severity: str, code: str, message: str) -> None:
        flags.append({"severity": severity, "code": code, "message": message})

    by_type = summary["against_by_type"]
    if by_type["criminal"]["count"]:
        flag("red", "criminal_cases",
             f"{by_type['criminal']['count']} criminal proceeding(s) against the company, its promoters or directors")
    if by_type["sebi_disciplinary"]["count"]:
        flag("red", "sebi_action", "Disciplinary action by SEBI or a stock exchange against the promoters")
    if by_type["regulatory"]["count"]:
        flag("amber", "regulatory_actions",
             f"{by_type['regulatory']['count']} action(s) by regulators or statutory authorities")
    share = summary["amount_pct_of_net_worth"]
    if share is not None and share >= 10:
        flag("red" if share >= 25 else "amber", "large_claims",
             f"Claims against the company, promoters and directors total ₹{summary['total_amount_against_million']:,.1f} m, "
             f"{share:g}% of net worth")
    if by_type["tax"]["count"]:
        flag("info", "tax_cases",
             f"{by_type['tax']['count']} tax proceeding(s) involving ₹{by_type['tax']['amount_million']:,.1f} m")
    if approvals:
        if approvals["not_applied"]:
            flag("amber", "approvals_not_applied",
                 f"{len(approvals['not_applied'])} required approval(s) not yet applied for")
        if approvals["pending"]:
            flag("info", "approvals_pending", f"{len(approvals['pending'])} approval(s) applied for but not yet received")
        if approvals["all_material_obtained"] is False:
            flag("amber", "approvals_missing", "The document says some material approvals are missing")
    return flags


def legal_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 5 as a LangGraph node: reads the legal chapters, adds state["legal"]."""
    run = AgentRun("legal", LEGAL_AGENT_MODEL, writer)
    reader = Evidence(state["file_path"], state["parsed"])
    results, warnings, errors = {}, [], []

    batches = _page_batches(reader.section_texts("litigation"))
    cases = []
    try:
        for i, batch in enumerate(batches, 1):
            run.say(f"reading litigation pages {batch[0][0]}–{batch[-1][0]} (call {i} of {len(batches)})")
            evidence = Evidence(state["file_path"], state["parsed"])
            for page, text in batch:
                evidence.add_text(page, text)
            excerpts = evidence.render(BATCH_TOKENS + 100)
            answer = run.ask(CASES_PROMPT.format(excerpts=excerpts), CaseBatch, CASES_OUTPUT_TOKENS)
            cases += [_case_record(c, evidence, warnings) for c in answer.cases]
        cases = _dedupe(cases)
        _mark_totals(cases)
        results["cases"] = cases
        results["summary"] = _summarise(cases, _net_worth(state["parsed"]))
    except LLM_ERRORS as exc:
        errors.append(f"litigation: {exc}")

    evidence = Evidence(state["file_path"], state["parsed"])
    pages = reader.section_texts("approvals")
    for page, text in pages[:1] + [p for p in pages[1:] if PENDING_WORDING.search(p[1])]:
        evidence.add_text(page, text)
    excerpts = evidence.render(APPROVALS_TOKENS)
    run.say(f"reading the approvals chapter ({len(evidence.pages)} pages)")
    try:
        answer = run.ask(APPROVALS_PROMPT.format(excerpts=excerpts), Approvals, APPROVALS_OUTPUT_TOKENS)
        results["approvals"] = {
            "all_material_obtained": answer.all_material_obtained,
            "pending": answer.pending,
            "not_applied": answer.not_applied,
            "pages": evidence.cited(answer.pages),
        }
    except LLM_ERRORS as exc:
        errors.append(f"approvals: {exc}")

    if "summary" in results:
        results["flags"] = _legal_flags(results["summary"], results.get("approvals"))
    if errors:
        return {"legal": run.failed("; ".join(errors), **results, warnings=warnings)}
    return {"legal": run.done(**results, warnings=warnings)}
