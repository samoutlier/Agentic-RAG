"""Agent 7: Synthesis. Writes the report's summary, bull and bear cases and
things to check, from the other agents' outputs only (never the document).

Python first turns those outputs into a numbered list of facts (F1 for
financial, R2 for risk, and so on), each keeping the pages it came from.
The model must cite fact ids for every point, so each sentence in the
report traces back to a page of the document. The rating is the rubric's,
decided in Python; the model explains it rather than choosing it.
"""
import re

from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.checks import unsupported_figures
from app.agents.state import AnalysisState
from app.config import SYNTHESIS_AGENT_MODEL

DISCLAIMER = (
    "This is an educational analysis generated automatically from the offer document by AI models. "
    "It may contain errors, covers only what the document discloses, and is not investment advice. "
    "Read the offer document itself and consult a SEBI-registered investment adviser before investing."
)


class Point(BaseModel):
    text: str
    facts: list[str] = []


class Synthesis(BaseModel):
    executive_summary: str
    bull_case: list[Point] = []
    bear_case: list[Point] = []
    check_before_investing: list[str] = []


PROMPT = """You are writing the summary of an educational analysis of an Indian IPO, using only the facts below. Each fact has an id like F3.

A scoring rubric rates this IPO "{rating}", {score}/100 ({parts}). Your writing must be consistent with that rating and explain what drives it.

Rules:
- Use only these facts. Don't add outside knowledge, and don't calculate new figures.
- Keep periods as the facts give them (say "in FY2022 and FY2023", not "in recent years").
- Every point lists the ids of the facts it relies on in its "facts" field; don't write ids in the text itself.
- Describe, don't advise: never tell the reader to buy, sell or subscribe.

Return:
- executive_summary: one paragraph of 120-180 words: what the company does, what the IPO money is for, the main strengths and concerns, and why the rubric lands where it does
- bull_case: 3 points in favour
- bear_case: 3 points against
- check_before_investing: 2-3 things a reader should verify before deciding

Facts:
{facts}"""

MAX_OUTPUT_TOKENS = 1500
MAX_TOP_RISKS = 8
# Fact ids the model sometimes writes into its sentences anyway: "(B1, F3)"
INLINE_IDS = re.compile(r"\s*\((?:[FRBOL]\d+[,;\s]*)+\)")


def _clean(text: str) -> str:
    return INLINE_IDS.sub("", text).strip()


class Facts:
    """The numbered facts, grouped by a letter for the agent they came from."""

    def __init__(self):
        self.items: list[dict] = []

    def add(self, prefix: str, text: str | None, pages=()) -> None:
        if not text:
            return
        number = sum(item["id"][0] == prefix for item in self.items) + 1
        self.items.append({"id": f"{prefix}{number}", "text": text.strip(), "pages": sorted(set(pages))})

    def claim(self, prefix: str, claim: dict | None, label: str = "") -> None:
        if claim:
            self.add(prefix, f"{label}{claim['text']}", claim["pages"])

    def text(self) -> str:
        return "\n".join(f"{f['id']}: {f['text']}" for f in self.items)


def _collect_facts(state: AnalysisState) -> Facts:
    facts = Facts()
    financial = state.get("financial") or {}
    if financial.get("scorecard"):
        pages = list((financial.get("pages") or {}).values())
        facts.add("F", (financial.get("assessment") or {}).get("summary"), pages)
        for s in financial["scorecard"]:
            facts.add("F", f"{s['dimension'].replace('_', ' ')}: {s['signal']}. {s['reason']}", pages)
        for f in financial.get("flags", []):
            facts.add("F", f"{f['severity']} flag: {f['message']}", pages)

    risk = state.get("risk") or {}
    if risk.get("register"):
        counts = risk["counts"]
        facts.add("R", f"{counts['total']} risk factors, average score {counts['average_score']} out of 5 "
                       f"({counts['by_severity']['high']} scored 4-5)")
        for r in [r for r in risk["register"] if (r["score"] or 0) >= 4][:MAX_TOP_RISKS]:
            facts.add("R", f"Risk factor {r['number']} ({r['category']}, score {r['score']}): {r['headline']}", [r["page"]])

    business = state.get("business") or {}
    profile = business.get("profile") or {}
    facts.claim("B", profile.get("description"), "What it does: ")
    for c in profile.get("strengths", []):
        facts.claim("B", c, "Strength: ")
    for c in profile.get("weaknesses", []):
        facts.claim("B", c, "Weakness: ")
    facts.claim("B", profile.get("market_position"), "Market position: ")
    promoters = business.get("promoters") or {}
    if promoters:
        names = ", ".join(p["name"] for p in promoters["people"])
        facts.add("B", f"Promoters: {names}. {promoters['holding_signal']['reason']}", promoters["holding_pages"])
        pledge = {False: "No promoter shares are pledged", True: "Some promoter shares are pledged"}.get(
            promoters["shares_pledged"])
        facts.add("B", pledge, promoters["pledge_source"]["pages"])
        for c in promoters.get("governance_concerns", []):
            facts.claim("B", c, "Governance: ")
        facts.claim("B", promoters.get("related_party"), "Related parties: ")

    offer = state.get("offer") or {}
    structure, metrics = offer.get("structure"), offer.get("metrics")
    if structure and metrics:
        pages = structure["pages"]
        if metrics["fresh_issue_million"]:
            facts.add("O", f"Fresh issue of ₹{metrics['fresh_issue_million']:,.1f} m", pages)
        elif structure["fresh_issue_shares"]:
            facts.add("O", f"Fresh issue of {structure['fresh_issue_shares']:,} shares (price not yet fixed)", pages)
        if structure["selling_shareholders"]:
            facts.add("O", f"Offer for sale by {', '.join(structure['selling_shareholders'])}", pages)
        for o in structure["objects"]:
            amount = f": {o['amount']:,} {structure['amount_unit']}" if o["amount"] is not None else ""
            facts.add("O", f"Use of proceeds: {o['purpose']}{amount}", o["pages"])
        for f in offer.get("flags", []):
            facts.add("O", f["message"], pages)
    peers = offer.get("peers")
    if peers and peers.get("peer_pe_average") is not None:
        facts.add("O", f"Listed peers' P/E: {peers['peer_pe_low']} to {peers['peer_pe_high']}, "
                       f"average {peers['peer_pe_average']}", peers["pages"])

    legal = state.get("legal") or {}
    summary = legal.get("summary")
    if summary:
        cases = "; ".join(f"{k.replace('_', ' ')} {v['count']}" for k, v in summary["against_by_type"].items() if v["count"])
        facts.add("L", f"Cases against the company, promoters and directors: {cases or 'none material'}. "
                       f"Claims total ₹{summary['total_amount_against_million']:,.1f} m"
                       + (f" ({summary['amount_pct_of_net_worth']:g}% of net worth)"
                          if summary["amount_pct_of_net_worth"] is not None else ""),
                  sorted({c["page"] for c in legal.get("cases", []) if c["against_party"]}))
        for f in legal.get("flags", []):
            facts.add("L", f["message"])
    approvals = legal.get("approvals") or {}
    for item in approvals.get("pending", [])[:3]:
        facts.add("L", f"Approval pending: {item}", approvals.get("pages", []))
    return facts


def _point(point: Point, by_id: dict, warnings: list[str], label: str) -> dict:
    cited = [f for f in point.facts if f in by_id]
    if len(cited) < len(point.facts):
        warnings.append(f"{label}: dropped unknown fact ids {sorted(set(point.facts) - set(cited))}")
    pages = sorted({p for f in cited for p in by_id[f]["pages"]})
    return {"text": _clean(point.text), "facts": cited, "pages": pages}


def synthesis_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 7 as a LangGraph node: reads every agent's output and the
    score, adds state["report"]."""
    run = AgentRun("synthesis", SYNTHESIS_AGENT_MODEL, writer)
    score = state["score"]
    facts = _collect_facts(state)
    by_id = {f["id"]: f for f in facts.items}
    parts = ", ".join(f"{p['label']} {p['points']:g}/{p['max_points']:g}" for p in score["parts"])
    prompt = PROMPT.format(rating=score["rating"], score=score["score"], parts=parts, facts=facts.text())
    report = {"rating": score["rating"], "score": score["score"], "disclaimer": DISCLAIMER, "facts": facts.items}

    run.say(f"writing the summary from {len(facts.items)} facts")
    try:
        answer = run.ask(prompt, Synthesis, MAX_OUTPUT_TOKENS)
    except LLM_ERRORS as exc:
        # The score, rating and facts stand without the written summary
        return {"report": run.failed(exc, **report)}

    warnings = []
    written = " ".join([answer.executive_summary] + [p.text for p in answer.bull_case + answer.bear_case])
    unsupported = unsupported_figures(written, facts.text() + prompt)
    if unsupported:
        warnings.append(f"Figures not found in the facts: {', '.join(unsupported)}")
    return {"report": run.done(
        **report,
        executive_summary=_clean(answer.executive_summary),
        bull_case=[_point(p, by_id, warnings, "bull case") for p in answer.bull_case[:3]],
        bear_case=[_point(p, by_id, warnings, "bear case") for p in answer.bear_case[:3]],
        check_before_investing=[_clean(c) for c in answer.check_before_investing[:3]],
        warnings=warnings,
    )}
