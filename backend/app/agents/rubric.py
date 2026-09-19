"""The 0–100 score and the rating, computed in Python from the agents'
structured outputs. No LLM is involved, so the same analysis always gets
the same score, and every point gained or lost has a written reason.

    Financial health       30   Agent 2's scorecard and red flags
    Risk factors           20   Agent 1's risk scores
    Business & promoters   20   Agent 3's promoter stake, pledges, governance
    Legal & approvals      15   Agent 5's cases and missing approvals
    Offer structure        15   Agent 4's offer for sale and use of proceeds

A part whose agent failed gets half its points and is marked incomplete.

Knockout rules cap the rating at "Neutral", whatever the total: weak
financial health (under 40% of its points), or a criminal case or SEBI
action against the company, promoters or directors. Strength elsewhere
shouldn't outweigh either.

The weights and deductions are judgement calls, written down so anyone can
see and change them: this is an educational tool, not investment advice.
"""
from dataclasses import dataclass, field

RATINGS = [(65, "Leans Subscribe"), (45, "Neutral"), (0, "Leans Avoid")]
SIGNAL_POINTS = {"positive": 1.0, "neutral": 0.5, "negative": 0.0, "unknown": 0.5}
PLEDGE_WORDS = {False: "no", True: "yes", None: "not stated"}


@dataclass
class Part:
    name: str
    label: str
    max_points: float
    points: float = 0.0
    reasons: list[str] = field(default_factory=list)
    complete: bool = True

    def deduct(self, amount: float, reason: str) -> None:
        self.points -= amount
        self.reasons.append(f"-{amount:g}: {reason}")

    def result(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "points": round(min(max(self.points, 0), self.max_points), 1),
            "max_points": self.max_points,
            "reasons": self.reasons,
            "complete": self.complete,
        }


def _unavailable(part: Part, agent: str) -> Part:
    part.points = part.max_points / 2
    part.complete = False
    part.reasons.append(f"{agent} didn't finish, so this part gets half marks")
    return part


def _financial(output: dict | None) -> Part:
    part = Part("financial", "Financial health", 30)
    if not output or not output.get("scorecard"):
        return _unavailable(part, "The financial agent")
    signals = [s["signal"] for s in output["scorecard"]]
    part.points = 30 * sum(SIGNAL_POINTS[s] for s in signals) / len(signals)
    counts = {s: signals.count(s) for s in ("positive", "neutral", "negative")}
    part.reasons.append(f"Scorecard: {counts['positive']} positive, {counts['neutral']} neutral, "
                        f"{counts['negative']} negative of {len(signals)}")
    penalty = 0
    for flag in output.get("flags", []):
        cost = {"red": 3, "amber": 1}.get(flag["severity"], 0)
        if cost and penalty + cost <= 12:  # flags can take off at most 12
            penalty += cost
            part.deduct(cost, flag["message"])
    return part


def _risk(output: dict | None) -> Part:
    part = Part("risk", "Risk factors", 20)
    counts = (output or {}).get("counts") or {}
    if output is None or output.get("status") != "done" or counts.get("average_score") is None:
        return _unavailable(part, "The risk agent")
    average = counts["average_score"]
    # An average of 1 (all boilerplate) earns 20; an average of 5 earns 0
    part.points = 20 * (5 - average) / 4
    part.reasons.append(f"Average risk score {average:g} out of 5 across {counts['total']} risk factors")
    severe = counts["by_score"].get(5) or counts["by_score"].get("5") or 0
    if severe:
        part.deduct(min(2 * severe, 8), f"{severe} risk(s) scored 5, a threat to the core business")
    return part


def _business(output: dict | None) -> Part:
    part = Part("business", "Business & promoters", 20)
    promoters = (output or {}).get("promoters")
    if not promoters:
        return _unavailable(part, "The business agent")
    level = promoters["holding_signal"]["level"]
    holding = {"high": 10, "moderate": 6, "low": 2, "unknown": 5}[level]
    part.points += holding
    part.reasons.append(f"+{holding}: {promoters['holding_signal']['reason']} ({level} stake)")
    pledged = promoters["shares_pledged"]
    pledge = {False: 4, True: 0, None: 2}[pledged]
    part.points += pledge
    part.reasons.append(f"+{pledge}: promoter shares pledged: {PLEDGE_WORDS[pledged]}")
    concerns = promoters.get("governance_concerns") or []
    governance = max(6 - 1.5 * len(concerns), 0)
    part.points += governance
    part.reasons.append(f"+{governance:g}: {len(concerns)} governance concern(s) found")
    return part


def _legal(output: dict | None) -> Part:
    part = Part("legal", "Legal & approvals", 15)
    summary = (output or {}).get("summary")
    if not summary:
        return _unavailable(part, "The legal agent")
    part.points = 15
    by_type = summary["against_by_type"]
    if by_type["criminal"]["count"]:
        part.deduct(min(4 * by_type["criminal"]["count"], 8), f"{by_type['criminal']['count']} criminal case(s) against")
    if by_type["sebi_disciplinary"]["count"]:
        part.deduct(5, "SEBI or stock exchange action against the promoters")
    if by_type["regulatory"]["count"]:
        part.deduct(min(1.5 * by_type["regulatory"]["count"], 4.5),
                    f"{by_type['regulatory']['count']} regulatory action(s) against")
    share = summary["amount_pct_of_net_worth"]
    if share is not None and share >= 10:
        part.deduct(5 if share >= 25 else 3, f"claims against total {share:g}% of net worth")
    approvals = output.get("approvals") or {}
    if approvals.get("not_applied"):
        part.deduct(min(len(approvals["not_applied"]), 3), "required approvals not yet applied for")
    if approvals.get("all_material_obtained") is False:
        part.deduct(2, "the document says material approvals are missing")
    if not part.reasons:
        part.reasons.append("No criminal, regulatory or large claims against the company, promoters or directors")
    return part


def _offer(output: dict | None) -> Part:
    part = Part("offer", "Offer structure", 15)
    metrics = (output or {}).get("metrics")
    if not metrics:
        return _unavailable(part, "The offer agent")
    part.points = 15
    ofs = metrics["offer_for_sale_pct_of_shares_offered"]
    if ofs is not None and ofs >= 25:
        part.deduct(5 if ofs >= 50 else 2, f"{ofs:g}% of the shares offered are sold by existing shareholders")
    codes = {f["code"] for f in output.get("flags", [])}
    if "promoters_selling" in codes:
        part.deduct(2, "promoters or the promoter group are selling shares")
    if "vague_use_of_proceeds" in codes:
        part.deduct(3, "over 20% of the fresh issue isn't tied to a stated use")
    if not part.reasons:
        part.reasons.append("No concerns in how the offer is structured")
    return part


def _risk_reward(parts: dict[str, dict]) -> dict:
    """Reward from financial health; risk from the risk factors and legal
    parts. Each is 'higher' or 'lower' against the middle of its range."""
    reward = parts["financial"]["points"] / parts["financial"]["max_points"]
    safety = (parts["risk"]["points"] / parts["risk"]["max_points"]
              + parts["legal"]["points"] / parts["legal"]["max_points"]) / 2
    reward_label = "Higher reward" if reward >= 0.6 else "Lower reward"
    risk_label = "lower risk" if safety >= 0.6 else "higher risk"
    return {"reward": round(reward, 2), "safety": round(safety, 2), "quadrant": f"{reward_label}, {risk_label}"}


def score_analysis(state: dict) -> dict:
    """The score, rating, per-part breakdown and risk-reward position."""
    parts = [
        _financial(state.get("financial")),
        _risk(state.get("risk")),
        _business(state.get("business")),
        _legal(state.get("legal")),
        _offer(state.get("offer")),
    ]
    results = {part.name: part.result() for part in parts}
    total = round(sum(r["points"] for r in results.values()), 1)
    rating = next(label for threshold, label in RATINGS if total >= threshold)

    knockouts = []
    financial = results["financial"]
    if financial["complete"] and financial["points"] < 0.4 * financial["max_points"]:
        knockouts.append(f"Financial health scored {financial['points']:g}/{financial['max_points']:g}, under 40%")
    legal_codes = {f["code"] for f in (state.get("legal") or {}).get("flags", []) if f["severity"] == "red"}
    if legal_codes & {"criminal_cases", "sebi_action"}:
        knockouts.append("Criminal or SEBI proceedings against the company, promoters or directors")
    if knockouts and rating == "Leans Subscribe":
        rating = "Neutral"

    return {
        "score": total,
        "rating": rating,
        "knockouts": knockouts,  # listed even when they didn't change the rating
        "parts": list(results.values()),
        "incomplete": [r["label"] for r in results.values() if not r["complete"]],
        "risk_reward": _risk_reward(results),
    }
