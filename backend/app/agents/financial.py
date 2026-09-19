"""Agent 2: Financial Health. The ratios, scorecard and red flags are
computed in Python (ratios.py); the LLM reads them and explains what they
add up to, tying every point to the metrics it relies on.

It uses only Agent 0's summary financials, not the search index, so it can
run while the index is still being built.
"""
from typing import Literal

from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.checks import unsupported_figures
from app.agents.ratios import GROWTH_SERIES, METRICS, analyse_financials
from app.agents.state import AnalysisState
from app.config import FINANCIAL_AGENT_MODEL

# The model may only cite metrics that exist: Literal[("revenue", ...)]
# is the same as Literal["revenue", ...], so Pydantic rejects anything else
MetricKey = Literal[tuple(METRICS)]


class Point(BaseModel):
    point: str
    metrics: list[MetricKey] = []


class FinancialAssessment(BaseModel):
    summary: str
    strengths: list[Point] = []
    concerns: list[Point] = []


PROMPT = """You are a financial analyst reviewing the summary financial statements of a company planning an IPO in India. All amounts are in ₹ million.
The ratios, scorecard and red flags below were calculated from its offer document. Explain what they mean for a retail investor.

Rules:
- Use only the figures given here. Don't calculate new ones or use outside knowledge.
- Columns marked "part-year" cover less than 12 months, so don't compare their totals with full years.
- An "unusual changes" flag may be a one-off event: say it needs checking rather than guessing a cause.
- For each point, list the metric keys (the first word of each table row) it relies on.

Ratios by period:
{table}

Growth per year, {span}:
{growth}

Scorecard:
{scorecard}

Red flags:
{flags}

Return:
- summary: 2-3 sentences on the company's overall financial health
- strengths: up to 3 points
- concerns: up to 4 points, most serious first"""

MAX_OUTPUT_TOKENS = 1000  # qwen3.8-27b allows 1,000 output tokens per minute


def _format(value: float | None, unit: str) -> str:
    if value is None:
        return "–"
    if unit == "₹ m":
        return f"{value:,.1f}"
    if unit == "%":
        return f"{value:.1f}%"
    if unit == "x":
        return f"{value:.2f}x"
    return f"{value:.0f}"  # days


def _prompt(analysis: dict) -> str:
    # Oldest full year first so trends read left to right; part-year last
    periods = [p for p in reversed(analysis["periods"]) if p["full_year"]]
    periods += [p for p in analysis["periods"] if not p["full_year"]]
    rows = ["metric | " + " | ".join(p["label"] + ("" if p["full_year"] else " (part-year)") for p in periods)]
    for key, (label, unit) in METRICS.items():
        values = [analysis["metrics"][key].get(p["label"]) for p in periods]
        if any(v is not None for v in values):
            rows.append(f"{key} ({label}, {unit}) | " + " | ".join(_format(v, unit) for v in values))

    growth = analysis["growth"]
    growth_lines = [
        f"- {name}: {growth[f'{key}_cagr']:.1f}%"
        for key, name in GROWTH_SERIES.items()
        if growth.get(f"{key}_cagr") is not None
    ]
    span = f"{growth['from']} to {growth['to']}" if growth else "not available"

    return PROMPT.format(
        table="\n".join(rows),
        span=span,
        growth="\n".join(growth_lines) or "- not available",
        scorecard="\n".join(f"- {s['dimension']}: {s['signal']} ({s['reason']})" for s in analysis["scorecard"]),
        flags="\n".join(f"- [{f['severity']}] {f['message']}" for f in analysis["flags"]) or "- none",
    )


def financial_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 2 as a LangGraph node: reads state["parsed"], adds state["financial"]."""
    run = AgentRun("financial", FINANCIAL_AGENT_MODEL, writer)
    if not state["parsed"]["financials"]["periods"]:
        return {"financial": run.failed("Agent 0 couldn't read the summary financial statements")}
    analysis = analyse_financials(state["parsed"]["financials"])
    red = sum(f["severity"] == "red" for f in analysis["flags"])
    run.say(f"ratios computed, {len(analysis['flags'])} flags ({red} red); asking the model to interpret them")

    prompt = _prompt(analysis)
    try:
        answer = run.ask(prompt, FinancialAssessment, MAX_OUTPUT_TOKENS)
    except LLM_ERRORS as exc:
        # The ratios, scorecard and flags don't need the LLM, so they're kept
        return {"financial": run.failed(exc, **analysis)}

    assessment = {
        "summary": answer.summary.strip(),
        "strengths": [p.model_dump() for p in answer.strengths[:3]],
        "concerns": [p.model_dump() for p in answer.concerns[:4]],
    }
    written = " ".join([assessment["summary"]] + [p["point"] for p in assessment["strengths"] + assessment["concerns"]])
    warnings = analysis.pop("warnings")
    unsupported = unsupported_figures(written, prompt)
    if unsupported:
        warnings.append(f"Figures in the assessment that aren't in the data: {', '.join(unsupported)}")
    return {"financial": run.done(**analysis, assessment=assessment, warnings=warnings)}
