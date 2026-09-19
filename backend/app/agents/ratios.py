"""Agent 2's arithmetic: ratios, a scorecard and red flags, computed in
Python from Agent 0's summary financials. The LLM only interprets these
numbers; it never calculates them.

Periods: documents give three financial years and often a part-year
("stub") period, such as the six months to 30 September. A part-year's
revenue or profit can't be compared with a full year's, so growth rates,
returns and "days" ratios use full years only. Balance-sheet ratios (debt
to equity, current ratio) use every period: a balance sheet is a snapshot,
and the latest one matters most.

The thresholds are general rules of thumb, not adjusted for the industry.
"""
import re

# key -> (label, unit)
METRICS = {
    "revenue": ("Revenue from operations", "₹ m"),
    "revenue_growth": ("Revenue growth", "%"),
    "ebitda": ("EBITDA", "₹ m"),
    "ebitda_margin": ("EBITDA margin", "%"),
    "pat": ("Profit after tax", "₹ m"),
    "pat_margin": ("PAT margin", "%"),
    "roe": ("Return on equity", "%"),
    "debt_to_equity": ("Debt to equity", "x"),
    "interest_coverage": ("Interest coverage", "x"),
    "current_ratio": ("Current ratio", "x"),
    "receivable_days": ("Receivable days", "days"),
    "inventory_days": ("Inventory days", "days"),
    "operating_cash_flow": ("Operating cash flow", "₹ m"),
    "cash_conversion": ("Operating cash flow / PAT", "x"),
    "free_cash_flow": ("Free cash flow", "₹ m"),
    "other_income_share": ("Other income / profit before tax", "%"),
}

# Growth rates measured from the first to the last full year
GROWTH_SERIES = {
    "revenue": "Revenue",
    "ebitda": "EBITDA",
    "pat": "Profit after tax",
    "trade_receivables": "Trade receivables",
    "borrowings": "Borrowings",
}

# Items checked for unusual jumps. Balance-sheet items are compared with
# the period before (including a part-year); cash flows only year on year.
BALANCE_ITEMS = {
    "cash_and_equivalents": "Cash and cash equivalents",
    "trade_receivables": "Trade receivables",
    "inventories": "Inventories",
    "total_current_assets": "Current assets",
    "total_current_liabilities": "Current liabilities",
    "borrowings": "Borrowings",
}
FLOW_ITEMS = {"operating_cash_flow": "Operating cash flow"}
JUMP_RATIO = 3         # a threefold rise, or a fall to a third
JUMP_MIN_SHARE = 0.05  # ...that moves at least 5% of total assets


def _div(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b == 0:
        return None
    return a / b


def _pct(a: float | None, b: float | None) -> float | None:
    ratio = _div(a, b)
    return None if ratio is None else ratio * 100


def _days(balance: float | None, revenue: float | None) -> float | None:
    """How many days of revenue a balance represents."""
    ratio = _div(balance, revenue)
    return None if ratio is None else ratio * 365


def _change_pct(old: float | None, new: float | None) -> float | None:
    if old is None or new is None or old <= 0:
        return None
    return (new / old - 1) * 100


def _cagr(first: float | None, last: float | None, years: int) -> float | None:
    """Compound annual growth rate, in %. Only defined when both values are positive."""
    if first is None or last is None or first <= 0 or last <= 0 or years <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100


def _years_between(first: str, last: str, count: int) -> int:
    a, b = re.fullmatch(r"FY(\d{4})", first), re.fullmatch(r"FY(\d{4})", last)
    return int(b[1]) - int(a[1]) if a and b else count - 1


def _period_metrics(value, full_year: bool) -> dict:
    """Every metric for one period; value(item) reads that period's figure."""
    revenue = value("revenue_from_operations")
    pbt, finance = value("profit_before_tax"), value("finance_costs")
    depreciation, other_income = value("depreciation"), value("other_income")
    pat, equity = value("profit_for_period"), value("total_equity")
    ocf, capex = value("operating_cash_flow"), value("capex")

    # Operating EBITDA: profit before tax, interest and depreciation, less
    # other income (interest earned, one-off gains) that isn't from the business
    ebitda = None
    if None not in (pbt, finance, depreciation):
        ebitda = pbt + finance + depreciation - (other_income or 0)

    return {
        "revenue": revenue,
        "ebitda": ebitda,
        "ebitda_margin": _pct(ebitda, revenue),
        "pat": pat,
        "pat_margin": _pct(pat, revenue),
        # A part-year's profit and sales would understate these three
        "roe": _pct(pat, equity) if full_year and equity and equity > 0 else None,
        "receivable_days": _days(value("trade_receivables"), revenue) if full_year else None,
        "inventory_days": _days(value("inventories"), revenue) if full_year else None,
        "debt_to_equity": _div(value("borrowings"), equity) if equity and equity > 0 else None,
        # Operating profit (before interest) divided by the interest bill
        "interest_coverage": _div(pbt + finance, finance) if pbt is not None and finance else None,
        "current_ratio": _div(value("total_current_assets"), value("total_current_liabilities")),
        "operating_cash_flow": ocf,
        "cash_conversion": _div(ocf, pat) if pat and pat > 0 else None,
        "free_cash_flow": ocf - abs(capex) if ocf is not None and capex is not None else None,
        "other_income_share": _pct(other_income, pbt) if pbt and pbt > 0 else None,
    }


def _grade(value: float | None, good: float, bad: float, higher_is_better: bool = True) -> str:
    if value is None:
        return "unknown"
    if not higher_is_better:
        value, good, bad = -value, -good, -bad
    return "positive" if value >= good else "negative" if value < bad else "neutral"


def _scorecard(m: dict, growth: dict, full_years: list[str], latest: str) -> list[dict]:
    """Seven dimensions, each graded positive / neutral / negative with its reason."""
    card = []

    def add(dimension: str, signal: str, reason: str) -> None:
        card.append({"dimension": dimension, "signal": signal, "reason": reason})

    if not full_years:
        return [{"dimension": "all", "signal": "unknown", "reason": "No full financial years found"}]
    first, last = full_years[-1], full_years[0]
    span = f"{first}→{last}"

    cagr = growth.get("revenue_cagr")
    if cagr is None:
        add("growth", "unknown", "Not enough full years to measure revenue growth")
    else:
        verb = "grew" if cagr >= 0 else "shrank"
        add("growth", _grade(cagr, 15, 5), f"Revenue {verb} {abs(cagr):.1f}% a year ({span})")

    margin_first, margin_last = m["ebitda_margin"].get(first), m["ebitda_margin"].get(last)
    pats = {fy: m["pat"].get(fy) for fy in full_years}
    if margin_first is None or margin_last is None or None in pats.values():
        add("profitability", "unknown", "Margins couldn't be calculated")
    else:
        change = margin_last - margin_first
        loss_years = [fy for fy, pat in pats.items() if pat < 0]
        if pats[last] < 0 or change <= -3:
            signal = "negative"
        elif not loss_years and change >= 1:
            signal = "positive"
        else:
            signal = "neutral"
        profit_note = f"losses in {', '.join(loss_years)}" if loss_years else "profitable every year"
        add("profitability", signal, f"EBITDA margin {margin_first:.1f}% → {margin_last:.1f}% ({span}); {profit_note}")

    de, cover = m["debt_to_equity"].get(latest), m["interest_coverage"].get(last)
    if de is None:
        add("leverage", "unknown", "Debt to equity couldn't be calculated")
    else:
        if de > 1.5 or (cover is not None and cover < 2):
            signal = "negative"
        elif de <= 0.5 and (cover is None or cover >= 3):
            signal = "positive"
        else:
            signal = "neutral"
        cover_note = f"; operating profit covers interest {cover:.1f}x ({last})" if cover is not None else ""
        add("leverage", signal, f"Debt to equity {de:.2f}x ({latest}){cover_note}")

    current = m["current_ratio"].get(latest)
    add("liquidity", _grade(current, 1.5, 1.0),
        f"Current ratio {current:.2f}x ({latest})" if current is not None else "Current ratio couldn't be calculated")

    ocfs = {fy: m["operating_cash_flow"].get(fy) for fy in full_years}
    negative_years = [fy for fy, ocf in ocfs.items() if ocf is not None and ocf < 0]
    total_ocf = sum(ocf for ocf in ocfs.values() if ocf is not None)
    total_pat = sum(pat for pat in pats.values() if pat is not None)
    if all(ocf is None for ocf in ocfs.values()):
        add("cash_conversion", "unknown", "No operating cash flow figures")
    elif negative_years:
        add("cash_conversion", "negative", f"Operating cash flow was negative in {', '.join(negative_years)}")
    elif total_pat > 0:
        ratio = total_ocf / total_pat
        add("cash_conversion", _grade(ratio, 0.8, 0.5),
            f"Operating cash flow was {ratio:.2f}x profit after tax over {span}")
    else:
        add("cash_conversion", "positive", "Operating cash flow was positive every year despite accounting losses")

    changes, notes = [], []
    for key, name in (("receivable_days", "receivable days"), ("inventory_days", "inventory days")):
        a, b = m[key].get(first), m[key].get(last)
        if a is not None and b is not None:
            changes.append(b - a)
            notes.append(f"{name} {a:.0f} → {b:.0f}")
    if not changes:
        add("working_capital", "unknown", "Receivable and inventory days couldn't be calculated")
    else:
        if any(c >= 20 for c in changes) or (m["receivable_days"].get(last) or 0) >= 120:
            signal = "negative"
        elif all(c <= 5 for c in changes):
            signal = "positive"
        else:
            signal = "neutral"
        add("working_capital", signal, f"{'; '.join(notes).capitalize()} ({span})")

    roe = m["roe"].get(last)
    add("returns", _grade(roe, 15, 8),
        f"Return on equity {roe:.1f}% ({last})" if roe is not None else "Return on equity couldn't be calculated")
    return card


def _jumps(items: dict, labels: list[str], full_years: list[str]) -> list[dict]:
    """Balance-sheet or cash-flow items that changed unusually sharply, one
    flag per pair of periods (several items moving together are usually one
    event). Often a one-off, worth checking in the notes to the accounts."""
    changes: dict[tuple[str, str], list[str]] = {}
    for item, name in {**BALANCE_ITEMS, **FLOW_ITEMS}.items():
        series = items.get(item, {})
        periods = full_years if item in FLOW_ITEMS else labels
        for older, newer in zip(periods[1:], periods):
            a, b = series.get(older), series.get(newer)
            assets = items.get("total_assets", {}).get(newer)
            if not a or not b or a <= 0 or b <= 0 or not assets:
                continue
            ratio = b / a
            if (ratio >= JUMP_RATIO or ratio <= 1 / JUMP_RATIO) and abs(b - a) >= JUMP_MIN_SHARE * assets:
                change = f"up {ratio:.1f}x" if ratio > 1 else f"down {(1 - ratio) * 100:.0f}%"
                changes.setdefault((older, newer), []).append(f"{name} {change} (₹{a:,.1f} m → ₹{b:,.1f} m)")
    return [
        {
            "severity": "amber",
            "code": "unusual_jump",
            "message": f"Unusual changes from {older} to {newer}: {'; '.join(parts)}. "
                       "Worth checking in the notes to the accounts",
            "metrics": [],
        }
        for (older, newer), parts in sorted(changes.items(), key=lambda pair: labels.index(pair[0][1]))
    ]


def _flags(m: dict, growth: dict, items: dict, labels: list[str], full_years: list[str]) -> list[dict]:
    """Rule-based red (serious) and amber (worth a look) flags."""
    flags = []

    def flag(severity: str, code: str, message: str, metrics: list[str]) -> None:
        flags.append({"severity": severity, "code": code, "message": message, "metrics": metrics})

    latest = labels[0]
    first, last = (full_years[-1], full_years[0]) if full_years else (None, None)

    losses = [(p, v) for p in labels if (v := m["pat"].get(p)) is not None and v < 0]
    if losses:
        flag("red", "losses", "Net loss in " + ", ".join(f"{p} (₹{v:,.1f} m)" for p, v in losses), ["pat"])

    negative_ocf = [(p, v) for p in labels if (v := m["operating_cash_flow"].get(p)) is not None and v < 0]
    if negative_ocf:
        severity = "red" if any(p in full_years for p, _ in negative_ocf) else "amber"
        flag(severity, "negative_cash_flow",
             "Operating cash flow was negative in " + ", ".join(f"{p} (₹{v:,.1f} m)" for p, v in negative_ocf),
             ["operating_cash_flow"])
    elif full_years:
        total_pat = sum(v for fy in full_years if (v := m["pat"].get(fy)) is not None)
        total_ocf = sum(v for fy in full_years if (v := m["operating_cash_flow"].get(fy)) is not None)
        if total_pat > 0 and total_ocf / total_pat < 0.5:
            flag("amber", "weak_cash_conversion",
                 f"Only {total_ocf / total_pat * 100:.0f}% of profit after tax turned into operating cash ({first}→{last})",
                 ["cash_conversion"])

    a, b = m["ebitda_margin"].get(first), m["ebitda_margin"].get(last)
    if a is not None and b is not None and b - a <= -3:
        flag("red" if b - a <= -6 else "amber", "falling_margin",
             f"EBITDA margin fell from {a:.1f}% ({first}) to {b:.1f}% ({last})", ["ebitda_margin"])

    de, de_first = m["debt_to_equity"].get(latest), m["debt_to_equity"].get(first)
    if de is not None and de > 1.0:
        flag("red" if de > 1.5 else "amber", "high_debt", f"Debt is {de:.2f}x equity ({latest})", ["debt_to_equity"])
    debt_cagr, revenue_cagr = growth.get("borrowings_cagr"), growth.get("revenue_cagr")
    if de is not None and de_first is not None and de - de_first >= 0.3:
        flag("amber", "rising_debt", f"Debt to equity rose from {de_first:.2f}x ({first}) to {de:.2f}x ({latest})",
             ["debt_to_equity"])
    elif debt_cagr is not None and revenue_cagr is not None and debt_cagr - revenue_cagr >= 10:
        flag("amber", "rising_debt",
             f"Borrowings grew {debt_cagr:.1f}% a year, faster than revenue's {revenue_cagr:.1f}% ({first}→{last})",
             ["debt_to_equity", "revenue_growth"])

    cover = m["interest_coverage"].get(last)
    if cover is not None and cover < 2:
        flag("red" if cover < 1.5 else "amber", "low_interest_cover",
             f"Operating profit covered interest only {cover:.1f}x in {last}", ["interest_coverage"])

    current = m["current_ratio"].get(latest)
    if current is not None and current < 1:
        flag("amber", "low_liquidity",
             f"Current liabilities exceed current assets (current ratio {current:.2f}x, {latest})", ["current_ratio"])

    # Receivables growing much faster than sales, so that customers take
    # clearly longer to pay, can mean revenue is booked before it's really
    # earned: a classic sign of aggressive accounting
    receivables_cagr = growth.get("trade_receivables_cagr")
    days_first, days_last = m["receivable_days"].get(first), m["receivable_days"].get(last)
    if (receivables_cagr is not None and revenue_cagr is not None and receivables_cagr - revenue_cagr >= 10
            and days_first is not None and days_last is not None and days_last - days_first >= 10):
        flag("amber", "receivables_outpacing_revenue",
             f"Trade receivables grew {receivables_cagr:.1f}% a year against revenue's {revenue_cagr:.1f}%, "
             f"so customers took {days_first:.0f} → {days_last:.0f} days to pay ({first}→{last}): "
             "check how revenue is recognised", ["receivable_days", "revenue_growth"])
    if days_last is not None and days_last >= 120:
        flag("amber", "slow_collections", f"Customers take about {days_last:.0f} days to pay ({last})",
             ["receivable_days"])

    heavy = [(fy, v) for fy in full_years if (v := m["other_income_share"].get(fy)) is not None and v >= 25]
    if heavy:
        flag("amber", "other_income_dependence",
             "Other income was a large share of profit before tax: " + ", ".join(f"{v:.0f}% in {fy}" for fy, v in heavy),
             ["other_income_share"])

    flags.extend(_jumps(items, labels, full_years))
    flags.sort(key=lambda f: f["severity"] != "red")  # red first, otherwise in order
    return flags


def analyse_financials(financials: dict) -> dict:
    """Ratios for every period, growth rates, a scorecard and red flags,
    from Agent 0's summary financials (all amounts in ₹ million)."""
    periods = financials["periods"]  # newest first
    items = financials["items"]
    labels = [p["label"] for p in periods]
    full_years = [p["label"] for p in periods if p["full_year"]]

    metrics: dict[str, dict] = {key: {} for key in METRICS}
    for period in periods:
        label = period["label"]
        values = _period_metrics(lambda item: items.get(item, {}).get(label), period["full_year"])
        for key, value in values.items():
            metrics[key][label] = value
    for newer, older in zip(full_years, full_years[1:]):
        metrics["revenue_growth"][newer] = _change_pct(metrics["revenue"][older], metrics["revenue"][newer])

    growth: dict = {}
    if len(full_years) >= 2:
        first, last = full_years[-1], full_years[0]
        years = _years_between(first, last, len(full_years))
        growth = {"from": first, "to": last, "years": years}
        for name in GROWTH_SERIES:
            series = metrics[name] if name in metrics else items.get(name, {})
            growth[f"{name}_cagr"] = _cagr(series.get(first), series.get(last), years)

    scorecard = _scorecard(metrics, growth, full_years, labels[0])
    flags = _flags(metrics, growth, items, labels, full_years)

    def rounded(value):
        return round(value, 2) if isinstance(value, float) else value

    return {
        "unit": "₹ million",
        "reported_unit": financials["reported_unit"],
        "periods": periods,
        "metrics": {key: {p: rounded(v) for p, v in series.items()} for key, series in metrics.items()},
        "growth": {key: rounded(value) for key, value in growth.items()},
        "scorecard": scorecard,
        "flags": flags,
        "pages": financials["pages"],
        "warnings": list(financials["warnings"]),
    }
