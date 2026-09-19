"""The state that flows through the analysis graph.

LangGraph hands this dict to each node. A node reads what it needs and
returns only the keys it adds; LangGraph merges them into the state before
the next node runs. Every agent writes its own key, so agents that run at
the same time never overwrite each other's results.
"""
from typing import TypedDict


class AnalysisState(TypedDict, total=False):  # total=False: keys fill in as nodes run
    file_path: str     # the uploaded DRHP / RHP
    document_id: str   # from Agent 0; names the document's folder in ipo_data/
    parsed: dict       # Agent 0: sections, risk headings, summary financials
    risk: dict         # Agent 1: ranked risk register
    financial: dict    # Agent 2: ratios, scorecard, red flags, assessment
    business: dict     # Agent 3: business profile, promoters, governance
    offer: dict        # Agent 4: fresh issue vs offer for sale, use of proceeds, peers
    legal: dict        # Agent 5: cases against the company and promoters, approvals
    score: dict        # the rubric: 0-100 score, rating, breakdown (Python only)
    report: dict       # Agent 7: summary, bull and bear cases, cited facts
