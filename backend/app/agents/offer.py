"""Agent 4: Offer & Use of Proceeds. How much is a fresh issue (money for
the company) versus an offer for sale (money for existing shareholders),
what the company will spend its share on, and how the document compares
the company with listed peers.

The LLM only extracts figures, each checked against the excerpts it read.
Percentages and flags are computed here in Python. There's no P/E at the
issue price: the price band isn't in the DRHP or RHP.
"""
import re
from typing import Literal

from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.base import LLM_ERRORS, AgentRun
from app.agents.evidence import Evidence
from app.agents.state import AnalysisState
from app.config import OFFER_AGENT_MODEL
from app.drhp.financials import TO_MILLION
from app.drhp.parser import load_index

Unit = Literal["million", "lakh", "crore"]


# Optional fields have defaults, so a reply that leaves one out still counts


class UseOfProceeds(BaseModel):
    purpose: str
    amount: float | None = None  # in amount_unit; null when shown as [●]
    pages: list[int] = []


class OfferStructure(BaseModel):
    amount_unit: Unit
    fresh_issue_amount: float | None = None
    fresh_issue_shares: int | None = None
    offer_for_sale_shares: int | None = None
    selling_shareholders: list[str] = []
    promoters_selling: bool = False
    shares_before_offer: int | None = None
    shares_after_offer: int | None = None
    objects: list[UseOfProceeds] = []
    general_corporate_purposes_amount: float | None = None
    pages: list[int] = []


class Peer(BaseModel):
    name: str
    pe: float | None = None
    eps: float | None = None
    ronw_pct: float | None = None


class PeerComparison(BaseModel):
    peers: list[Peer] = []
    peer_pe_high: float | None = None
    peer_pe_low: float | None = None
    peer_pe_average: float | None = None
    company_ronw_pct: float | None = None
    company_nav_per_share: float | None = None
    pages: list[int] = []


RULES = """Rules:
- Use only these excerpts. A value shown as [●] or not given is null; never estimate it.
- Copy numbers exactly as printed, without commas (1,07,41,149 becomes 10741149).
- A number in brackets is negative: (0.76) means -0.76.
- pages: the page numbers of the excerpts you used."""

STRUCTURE_PROMPT = """You are extracting the structure of an Indian IPO from its offer document. Each excerpt starts with its page number, like [p.92].

{rules}

Return:
- amount_unit: the unit of the rupee amounts in the objects table: "million", "lakh" or "crore"
- fresh_issue_amount: the fresh issue size in amount_unit; fresh_issue_shares: the number of new shares
- offer_for_sale_shares: shares sold by existing shareholders (0 if there is no offer for sale)
- selling_shareholders: their names or descriptions (empty if none)
- promoters_selling: true if any promoter or promoter group member sells shares in the offer
- shares_before_offer and shares_after_offer: total equity shares outstanding
- objects: each use of the net proceeds with its amount in amount_unit, except general corporate purposes
- general_corporate_purposes_amount: in amount_unit

Excerpts:
{excerpts}"""

PEER_PROMPT = """You are extracting how an Indian IPO document compares the company with listed peers ("Basis for Offer Price"). Each excerpt starts with its page number, like [p.103].

{rules}

Return:
- peers: each listed peer company with its P/E, EPS (₹) and return on net worth (%), as printed
- peer_pe_high, peer_pe_low, peer_pe_average: the industry peer group P/E figures, if given
- company_ronw_pct: the company's own return on net worth for the latest full financial year
- company_nav_per_share: its net asset value per share at the latest full-year date

Excerpts:
{excerpts}"""

EVIDENCE_TOKENS = 3800
# qwen3.8-27b allows 1,000 output tokens per minute, and each call reserves
# its maximum. Replies here measure 200-400 tokens, so 600 lets both calls
# run in the same minute.
MAX_OUTPUT_TOKENS = 600
DEBT_PURPOSE = re.compile(r"repay|prepay|borrowing|loan|debt", re.IGNORECASE)


def _structure_evidence(state: AnalysisState, index) -> Evidence:
    evidence = Evidence(state["file_path"], state["parsed"], index)
    evidence.add_pages("the_offer", 1)  # the offer table: fresh issue, offer for sale, shares outstanding
    evidence.add_pages("objects", 2)    # the objects and the "Utilisation of Net Proceeds" table
    evidence.add_search("offer for sale by selling shareholders number of equity shares",
                        ["the_offer", "objects", "capital_structure"], k=2)
    evidence.add_search("general corporate purposes shall not exceed 25% of gross proceeds", ["objects"], k=1)
    return evidence


def _peer_evidence(state: AnalysisState, index) -> Evidence:
    evidence = Evidence(state["file_path"], state["parsed"], index)
    evidence.add_search("comparison of accounting ratios with listed industry peers EPS P/E RoNW NAV",
                        ["basis_for_price"], k=3)
    evidence.add_search("industry peer group P/E ratio highest lowest average", ["basis_for_price"], k=2)
    evidence.add_search("return on net worth weighted average", ["basis_for_price"], k=1)
    evidence.add_search("net asset value per equity share", ["basis_for_price"], k=1)
    return evidence


def _offer_metrics(s: OfferStructure) -> dict:
    """Shares and ₹ million figures the flags are based on (None when unknown)."""
    scale = TO_MILLION[s.amount_unit]
    fresh = s.fresh_issue_amount * scale if s.fresh_issue_amount is not None else None
    stated = [o.amount * scale for o in s.objects if o.amount is not None]
    specified = sum(stated) if stated else None
    debt = sum(o.amount * scale for o in s.objects if o.amount is not None and DEBT_PURPOSE.search(o.purpose))
    gcp = s.general_corporate_purposes_amount * scale if s.general_corporate_purposes_amount is not None else None

    def pct(part, whole):
        return round(part / whole * 100, 1) if part is not None and whole else None

    offered = None
    if s.fresh_issue_shares is not None and s.offer_for_sale_shares is not None:
        offered = s.fresh_issue_shares + s.offer_for_sale_shares
    return {
        "fresh_issue_million": fresh,
        "specified_objects_million": specified,
        "specified_pct_of_fresh_issue": pct(specified, fresh),
        # What the objects table doesn't pin down: general corporate
        # purposes plus issue expenses. SEBI caps the former at 25%.
        "unspecified_pct_of_fresh_issue": pct(fresh - specified, fresh) if fresh and specified is not None else None,
        "gcp_million": gcp,
        "gcp_pct_of_fresh_issue": pct(gcp, fresh),
        "debt_repayment_million": debt or None,
        "debt_pct_of_specified": pct(debt, specified) if debt else None,
        "offer_for_sale_pct_of_shares_offered": pct(s.offer_for_sale_shares, offered),
        # New shares as a share of all shares after the offer
        "dilution_pct": pct(s.fresh_issue_shares, s.shares_after_offer),
    }


def _offer_flags(m: dict, s: OfferStructure) -> list[dict]:
    flags = []

    def flag(severity: str, code: str, message: str) -> None:
        flags.append({"severity": severity, "code": code, "message": message})

    ofs = m["offer_for_sale_pct_of_shares_offered"]
    if ofs is not None and ofs >= 50:
        flag("amber", "mostly_offer_for_sale",
             f"{ofs:g}% of the shares on offer are sold by existing shareholders; that money goes to them, not the company")
    elif ofs:
        flag("info", "offer_for_sale", f"{ofs:g}% of the shares on offer are sold by existing shareholders")
    if s.promoters_selling:
        flag("amber", "promoters_selling", "Promoters or the promoter group are selling shares in the offer")
    if m["gcp_pct_of_fresh_issue"] is not None and m["gcp_pct_of_fresh_issue"] > 20:
        flag("amber", "vague_use_of_proceeds",
             f"{m['gcp_pct_of_fresh_issue']:g}% of the fresh issue is for general corporate purposes, which needn't be specified")
    elif m["gcp_pct_of_fresh_issue"] is None and (m["unspecified_pct_of_fresh_issue"] or 0) > 20:
        flag("amber", "vague_use_of_proceeds",
             f"Up to {m['unspecified_pct_of_fresh_issue']:g}% of the fresh issue isn't tied to a stated object "
             "(general corporate purposes plus issue expenses)")
    if m["debt_pct_of_specified"] is not None and m["debt_pct_of_specified"] >= 50:
        flag("info", "mostly_debt_repayment",
             f"{m['debt_pct_of_specified']:g}% of the stated uses repay borrowings: this lowers interest costs rather than funding growth")
    if m["dilution_pct"] is not None:
        flag("info", "dilution", f"New shares will make up {m['dilution_pct']:g}% of all shares after the offer")
    return flags


def offer_agent(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 4 as a LangGraph node: reads the document's index, adds state["offer"]."""
    run = AgentRun("offer", OFFER_AGENT_MODEL, writer)
    index = load_index(state["document_id"])
    results, warnings, errors = {}, [], []

    evidence = _structure_evidence(state, index)
    excerpts = evidence.render(EVIDENCE_TOKENS)
    run.say(f"reading the offer structure and objects ({len(evidence.pages)} pages of excerpts)")
    try:
        s = run.ask(STRUCTURE_PROMPT.format(rules=RULES, excerpts=excerpts), OfferStructure, MAX_OUTPUT_TOKENS)
        # Numbers not found in the excerpts are dropped before any maths
        for field in ("fresh_issue_amount", "fresh_issue_shares", "offer_for_sale_shares",
                      "shares_before_offer", "shares_after_offer", "general_corporate_purposes_amount"):
            setattr(s, field, evidence.number(getattr(s, field), field.replace("_", " "), warnings))
        for o in s.objects:
            o.amount = evidence.number(o.amount, f"amount for '{o.purpose[:40]}'", warnings)
            o.pages = evidence.cited(o.pages)
        metrics = _offer_metrics(s)
        results["structure"] = {**s.model_dump(), "pages": evidence.cited(s.pages)}
        results["metrics"] = metrics
        results["flags"] = _offer_flags(metrics, s)
    except LLM_ERRORS as exc:
        errors.append(f"offer structure: {exc}")

    evidence = _peer_evidence(state, index)
    excerpts = evidence.render(EVIDENCE_TOKENS)
    run.say(f"reading the peer comparison ({len(evidence.pages)} pages of excerpts)")
    try:
        p = run.ask(PEER_PROMPT.format(rules=RULES, excerpts=excerpts), PeerComparison, MAX_OUTPUT_TOKENS)
        for peer in p.peers:
            for field in ("pe", "eps", "ronw_pct"):
                setattr(peer, field, evidence.number(getattr(peer, field), f"{peer.name} {field}", warnings))
        for field in ("peer_pe_high", "peer_pe_low", "peer_pe_average", "company_ronw_pct", "company_nav_per_share"):
            setattr(p, field, evidence.number(getattr(p, field), field.replace("_", " "), warnings))
        results["peers"] = {**p.model_dump(), "pages": evidence.cited(p.pages)}
    except LLM_ERRORS as exc:
        errors.append(f"peer comparison: {exc}")

    if errors:
        return {"offer": run.failed("; ".join(errors), **results, warnings=warnings)}
    return {"offer": run.done(**results, warnings=warnings)}
