"""Agent 3: Business & Promoters. What the company does and how strong its
position looks; then who controls it, how much they own, and any governance
concerns.

Two LLM calls, each on excerpts gathered for it (the opening pages of the
relevant sections plus hybrid-search results). Every statement must cite
its pages; evidence.py drops citations of pages the model wasn't shown and
leaves out numbers that aren't in the excerpts.

Whether promoter shares are pledged comes from Python where possible: the
capital structure chapter states it in standard words, and a test model
misread "none ... is pledged" as a yes.
"""
import re

from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.evidence import Claim, Evidence
from app.agents.state import AnalysisState
from app.config import BUSINESS_AGENT_MODEL
from app.drhp.parser import load_index

# Optional fields have defaults, so a reply that leaves one out still counts


class BusinessProfile(BaseModel):
    description: Claim
    strengths: list[Claim] = []
    weaknesses: list[Claim] = []
    market_position: Claim | None = None


class Promoter(BaseModel):
    name: str
    role: str = ""
    background: str | None = None
    pages: list[int] = []


class PromoterProfile(BaseModel):
    promoters: list[Promoter] = []
    # Only the pre-offer figure: post-offer stakes are usually "[●]" until
    # the price is fixed, and a test model reported the pre-offer one instead
    pre_offer_holding_pct: float | None = None
    holding_pages: list[int] = []
    shares_pledged: bool | None = None
    related_party: Claim | None = None
    governance_concerns: list[Claim] = []


# SEBI's standard disclosure: "none of the Equity Shares held by our
# Promoters is/are pledged (or otherwise encumbered)"
NONE_PLEDGED = re.compile(
    r"none of the equity shares held by (?:our |the )?promoters?\b[^.]{0,120}?\b(?:is|are) pledged",
    re.IGNORECASE,
)


RULES = """Rules:
- Use only these excerpts. If something isn't in them, leave it out rather than guess.
- Every item cites the page numbers of the excerpts it comes from.
- Copy figures exactly as the excerpts give them; don't calculate new ones."""

BUSINESS_PROMPT = """You are analysing the business of a company planning an IPO in India, using excerpts from its offer document. Each excerpt starts with its page number, like [p.161].

{rules}

Return:
- description: what the company does: its products or services, main customers and where it operates (2-3 sentences)
- strengths: up to 4 competitive strengths that the excerpts back with facts
- weaknesses: up to 3 weaknesses or dependencies visible in the excerpts (for example reliance on a few customers, one plant or one region, small scale)
- market_position: its position against competitors or its market share, if the excerpts state it; otherwise null

Excerpts:
{excerpts}"""

PROMOTER_PROMPT = """You are assessing the promoters (the controlling shareholders) of a company planning an IPO in India, using excerpts from its offer document. Each excerpt starts with its page number, like [p.217].

{rules}

Return:
- promoters: each promoter's name, role (for example Managing Director, or a family trust), a one-sentence background if the excerpts give one, and pages
- pre_offer_holding_pct: the % of pre-offer share capital the promoters hold in total, as stated; null if not stated
- holding_pages: pages where that figure appears
- shares_pledged: true if any promoter shares are pledged or encumbered, false if the excerpts say none are, null if they don't say
- related_party: one sentence on the size and nature of related-party transactions, if given; otherwise null
- governance_concerns: up to 3 concrete issues the excerpts state, such as promoters' interests in businesses competing with the company, related-party dealings that are large for a company of this size, or past regulatory or legal action against promoters. Not a concern: a large promoter stake, ordinary salaries or standard disclosures. Empty if none

Excerpts:
{excerpts}"""

# Excerpts per call. With the instructions, schema and reply, each call
# stays around 6,000 tokens, inside one minute of the model's budget.
EVIDENCE_TOKENS = 4000
MAX_OUTPUT_TOKENS = 1500


def _business_evidence(state: AnalysisState, index) -> Evidence:
    evidence = Evidence(state["file_path"], state["parsed"], index)
    evidence.add_pages("business", 2)  # "Overview": what the company does, in its own words
    evidence.add_search("our competitive strengths", ["business"], k=3)
    evidence.add_search("revenue contribution from top customers and key products", ["business"], k=2)
    evidence.add_search("market share and position of the company among competitors", ["industry", "business"], k=2)
    evidence.add_search("our business strategies for growth", ["business"], k=1)
    return evidence


def _promoter_evidence(state: AnalysisState, index) -> Evidence:
    evidence = Evidence(state["file_path"], state["parsed"], index)
    evidence.add_pages("promoters", 1)  # names and combined holding
    evidence.add_search("shareholding of promoters and promoter group pre-offer and post-offer percentage",
                        ["capital_structure"], k=2)
    evidence.add_search("equity shares held by promoters pledged or encumbered", ["capital_structure"], k=2)
    evidence.add_search("brief biography of promoter director experience and qualifications", ["management"], k=2)
    evidence.add_search("promoters interest in other ventures in the same line of business conflict of interest",
                        ["promoters", "group_companies"], k=2)
    evidence.add_search("related party transactions with promoters directors and key managerial personnel",
                        ["related_party", "summary", "other_financial_info"], k=2)
    return evidence


def _holding_signal(holding: float | None) -> dict:
    """Promoters' pre-offer stake: a large one means they gain or lose with
    other shareholders. 50% is majority control; below 26% they can't block
    a special resolution on their own. The offer will dilute it somewhat."""
    if holding is None:
        return {"level": "unknown", "reason": "The promoters' holding isn't stated"}
    level = "high" if holding >= 50 else "moderate" if holding >= 26 else "low"
    return {"level": level, "reason": f"Promoters hold {holding:g}% before the offer"}


def business_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 3 as a LangGraph node: reads the document's index, adds state["business"]."""
    run = AgentRun("business", BUSINESS_AGENT_MODEL, writer)
    index = load_index(state["document_id"])
    results, warnings, errors = {}, [], []

    evidence = _business_evidence(state, index)
    excerpts = evidence.render(EVIDENCE_TOKENS)
    run.say(f"reading {len(evidence.pages)} pages of excerpts about the business")
    try:
        profile = run.ask(BUSINESS_PROMPT.format(rules=RULES, excerpts=excerpts), BusinessProfile, MAX_OUTPUT_TOKENS)
        results["profile"] = {
            "description": evidence.claim(profile.description, "description", warnings),
            "strengths": [evidence.claim(c, "strength", warnings) for c in profile.strengths[:4]],
            "weaknesses": [evidence.claim(c, "weakness", warnings) for c in profile.weaknesses[:3]],
            "market_position": evidence.claim(profile.market_position, "market position", warnings),
        }
    except LLM_ERRORS as exc:
        errors.append(f"business profile: {exc}")

    evidence = _promoter_evidence(state, index)
    excerpts = evidence.render(EVIDENCE_TOKENS)
    run.say(f"reading {len(evidence.pages)} pages of excerpts about the promoters")
    try:
        promoters = run.ask(PROMOTER_PROMPT.format(rules=RULES, excerpts=excerpts), PromoterProfile, MAX_OUTPUT_TOKENS)
        holding = evidence.number(promoters.pre_offer_holding_pct, "pre-offer holding", warnings)
        # The capital structure chapter's standard statement, if it makes one
        disclosure = evidence.scan("capital_structure", NONE_PLEDGED)
        if disclosure:
            pledged, pledge_source = False, disclosure
        else:  # no standard statement found: the model's reading, flagged as such
            pledged, pledge_source = promoters.shares_pledged, {"text": "model's reading of the excerpts", "pages": []}
        results["promoters"] = {
            "people": [
                {"name": p.name, "role": p.role, "background": p.background, "pages": evidence.cited(p.pages)}
                for p in promoters.promoters
            ],
            "pre_offer_holding_pct": holding,
            "holding_pages": evidence.cited(promoters.holding_pages),
            "holding_signal": _holding_signal(holding),
            "shares_pledged": pledged,
            "pledge_source": pledge_source,
            "related_party": evidence.claim(promoters.related_party, "related party", warnings),
            "governance_concerns": [evidence.claim(c, "governance", warnings) for c in promoters.governance_concerns[:3]],
        }
    except LLM_ERRORS as exc:
        errors.append(f"promoters: {exc}")

    if errors:
        return {"business": run.failed("; ".join(errors), **results, warnings=warnings)}
    return {"business": run.done(**results, warnings=warnings)}
