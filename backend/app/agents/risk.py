"""Agent 1: Risk Intelligence. Turns the Risk Factors section into a ranked
risk register.

It reads only the numbered risk headings Agent 0 extracted (50–80 per
document), not the 30–60 pages beneath them: each heading already states
its risk in a sentence or two. For every heading the LLM gives a short
plain-English headline, a category and a score from 1 to 5. Page numbers,
groups, severity labels, ranking and counts all come from Agent 0's data
in Python, so citations can't be made up.

Scores, not labels: asked for high / medium / low with "about one in five
high", the model marked anywhere from 4 to 22 risks high per document,
because each batch applied the quota its own way. A 1–5 scale with a
fixed description of each level is judged risk by risk instead.
"""
from typing import Annotated, Literal, get_args

from langgraph.types import StreamWriter
from pydantic import BaseModel, Field

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.checks import unsupported_figures
from app.agents.state import AnalysisState
from app.agents.structured import call_tokens
from app.config import GROQ_TOKENS_PER_MINUTE, RISK_AGENT_MODEL

Category = Literal[
    "business", "financial", "regulatory_legal", "litigation",
    "management", "macroeconomic", "offer_shares",
]
CATEGORIES = get_args(Category)
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
SEVERITY_OF_SCORE = {5: "high", 4: "high", 3: "medium", 2: "low", 1: "low"}


class ClassifiedRisk(BaseModel):
    number: int
    headline: str
    category: Category
    score: Annotated[int, Field(ge=1, le=5)]


class RiskBatch(BaseModel):
    risks: list[ClassifiedRisk]


PROMPT = """You are analysing the Risk Factors section of an Indian IPO offer document (DRHP or RHP).
Below are numbered risk-factor headings, under the group titles the document uses.

For EVERY numbered heading, return:
- number: the heading's number
- headline: the risk in at most 12 plain-English words. Keep figures the heading gives; never add figures it doesn't give.
- category, one of:
    business: customers, suppliers, competition, operations, capacity, technology, projects, employees
    financial: debt, cash flow, working capital, losses, contingent liabilities, funding, insurance
    regulatory_legal: licences, approvals, compliance, tax, changes in law or government policy, accounting standards, enforcing judgments
    litigation: court cases, proceedings or investigations involving the company, its promoters, directors or group companies
    management: reliance on key people, promoter control or conflicts of interest, related-party transactions, governance
    macroeconomic: the economy, inflation, interest or exchange rates, politics, natural disasters, industry-wide downturns
    offer_shares: the share price, listing, liquidity, dilution, dividends, taxes on selling the shares, bidding rules, how the IPO money is used, the offer for sale
- score, how serious the risk is for this company, judged on its own:
    5: could threaten the company's survival or its core business (for example doubts about continuing as a going concern, criminal or regulatory action against it or its promoters, losing a licence it can't operate without, one customer bringing most of the revenue)
    4: significant and specific to this company (for example most revenue from a few customers, one plant or one region; heavy debt; negative cash flow; large pending claims)
    3: a real risk for this company, but with moderate or uncertain impact
    2: minor, or an operational risk that most companies share
    1: standard wording found in almost every IPO document (for example share-price volatility, taxes on capital gains, enforcing foreign judgments, accounting standards, the Indian economy)

{headings}"""

# Each call must fit in one minute of the model's token budget, with room
# to spare because the 4-characters-per-token estimate is rough
CALL_TOKEN_LIMIT = int(GROQ_TOKENS_PER_MINUTE * 0.8)
# Measured on real documents: ~30 tokens per classified risk and under 50
# reasoning tokens per call at low effort. These leave generous headroom.
ANSWER_TOKENS_PER_RISK = 40
REASONING_TOKENS = 500
MAX_HEADING_CHARS = 1200     # guards against a heading merged with body text


def _prompt(batch: list[dict]) -> str:
    """The headings, under their group titles as in the document."""
    lines, group = [], None
    for risk in batch:
        if risk["group"] != group or not lines:
            group = risk["group"]
            lines.append(f"\n{group or 'Risk factors'}:")
        lines.append(f"{risk['number']}. {risk['text'][:MAX_HEADING_CHARS]}")
    return PROMPT.format(headings="\n".join(lines).strip())


def _max_output(batch: list[dict]) -> int:
    return ANSWER_TOKENS_PER_RISK * len(batch) + REASONING_TOKENS


def _split(risks: list[dict], parts: int) -> list[list[dict]]:
    """Split the headings, in order, into `parts` batches of similar length."""
    sizes = [len(r["text"]) for r in risks]
    target = sum(sizes) / parts
    batches: list[list[dict]] = [[] for _ in range(parts)]
    running = 0
    for risk, size in zip(risks, sizes):
        batches[min(int(running // target), parts - 1)].append(risk)
        running += size
    return [batch for batch in batches if batch]


def _batches(risks: list[dict]) -> list[list[dict]]:
    """As few batches as possible, each small enough for one call. Every
    call waits for room in the per-minute budget, so fewer calls is faster."""
    for parts in range(1, len(risks) + 1):
        batches = _split(risks, parts)
        if all(call_tokens(_prompt(b), RiskBatch, _max_output(b)) <= CALL_TOKEN_LIMIT for b in batches):
            return batches
    raise ValueError("A single risk heading is too long for one call")


def _classify(run: AgentRun, batch: list[dict]) -> dict[int, ClassifiedRisk]:
    """One LLM call for a batch; returns the answers by risk number.
    Answers about numbers that aren't in the batch are ignored."""
    answer = run.ask(_prompt(batch), RiskBatch, _max_output(batch))
    wanted = {risk["number"] for risk in batch}
    return {item.number: item for item in answer.risks if item.number in wanted}


def _shorten(text: str, words: int = 14) -> str:
    parts = text.split()
    return " ".join(parts[:words]) + ("…" if len(parts) > words else "")


def _build_register(risks: list[dict], answers: dict[int, ClassifiedRisk]) -> tuple[list[dict], list[str]]:
    """Join each heading (text, page, group) with its classification, then
    rank: highest score first, and within a score in the document's own order."""
    register, replaced = [], 0
    for risk in risks:
        answer = answers.get(risk["number"])
        if answer is None:
            register.append({**risk, "headline": _shorten(risk["text"]), "category": None,
                             "score": None, "severity": None})
            continue
        headline = answer.headline.strip()
        # A figure the heading doesn't contain was made up: use the heading's own words
        if unsupported_figures(headline, risk["text"]):
            headline = _shorten(risk["text"])
            replaced += 1
        register.append({**risk, "headline": headline, "category": answer.category,
                         "score": answer.score, "severity": SEVERITY_OF_SCORE[answer.score]})

    register.sort(key=lambda r: (-(r["score"] or 0), r["number"]))
    for rank, entry in enumerate(register, 1):
        entry["rank"] = rank

    warnings = []
    unclassified = [r["number"] for r in register if r["severity"] is None]
    if unclassified:
        warnings.append(f"The model didn't classify risks {unclassified}; they're listed last")
    if replaced:
        warnings.append(f"{replaced} headlines had figures not in the heading; the heading's words were used instead")
    return register, warnings


def _counts(register: list[dict]) -> dict:
    classified = [r for r in register if r["score"]]
    return {
        "total": len(register),
        "by_score": {s: sum(r["score"] == s for r in classified) for s in (5, 4, 3, 2, 1)},
        "by_severity": {s: sum(r["severity"] == s for r in classified) for s in SEVERITY_ORDER},
        "by_category": {c: sum(r["category"] == c for r in classified) for c in CATEGORIES},
        "average_score": round(sum(r["score"] for r in classified) / len(classified), 2) if classified else None,
    }


def risk_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 1 as a LangGraph node: reads state["parsed"], adds state["risk"]."""
    run = AgentRun("risk", RISK_AGENT_MODEL, writer)
    risks = state["parsed"]["risks"]
    if not risks:
        return {"risk": run.failed("Agent 0 found no numbered risk headings")}

    answers: dict[int, ClassifiedRisk] = {}
    try:
        batches = _batches(risks)
        for i, batch in enumerate(batches, 1):
            run.say(f"classifying risks {batch[0]['number']}–{batch[-1]['number']} (call {i} of {len(batches)})")
            answers.update(_classify(run, batch))
        # Small models occasionally skip an item in a long list: ask once more about those
        missing = [risk for risk in risks if risk["number"] not in answers]
        for batch in _batches(missing) if missing else []:
            run.say(f"asking again about {len(batch)} skipped risks")
            answers.update(_classify(run, batch))
    except LLM_ERRORS as exc:
        return {"risk": run.failed(exc)}

    register, warnings = _build_register(risks, answers)
    return {"risk": run.done(register=register, counts=_counts(register), warnings=warnings)}
