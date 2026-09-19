"""The analysis pipeline as a LangGraph graph.

                  ┌→ risk (Agent 1) ───────────────────┐
                  ├→ financial (Agent 2) ──────────────┤
    START → parse ┼→ legal (Agent 5) ──────────────────┼→ score → synthesis → END
     (Agent 0)    └→ index ─┬→ business (Agent 3) ─────┤  (rubric)  (Agent 7)
                            └→ offer (Agent 4) ────────┘

A node is a plain function: it gets the current state and returns the keys
it adds. Edges say which node runs next; several edges leaving one node run
their targets at the same time. Agents 1, 2 and 5 read the parsed data or
the PDF, so they run while the search index is built; Agents 3 and 4 search
the index, so they wait for it. "score" waits for all five agents (a join),
then the synthesis agent writes the report.

Agents on different Groq models never slow each other down (Groq limits
each model separately); agents sharing a model are paced by its budget.

Every LLM agent's output is saved as it finishes, and a saved successful
output is reused next time. So re-running an analysis that failed halfway
repeats only the agents that failed, and analysing the same file again
costs no tokens at all. (The rubric always re-runs: it's instant and should
reflect the current rules.)
"""
from typing import Callable

from langgraph.graph import END, START, StateGraph
from langgraph.types import StreamWriter

from app.agents.business import business_agent
from app.agents.financial import financial_agent
from app.agents.legal import legal_agent
from app.agents.offer import offer_agent
from app.agents.risk import risk_agent
from app.agents.rubric import score_analysis
from app.agents.state import AnalysisState
from app.agents.synthesis import synthesis_agent
from app.drhp.parser import index_offer_document, load_result, parse_offer_document, save_result

AGENTS = ["risk", "financial", "legal", "business", "offer"]


def reusable(name: str, key: str, node: Callable,
             still_valid: Callable[[dict, dict], bool] | None = None) -> Callable:
    """Wrap agent node `name` so its output (state[key]) is saved, and
    reused if this document already has a successful one. `still_valid(saved,
    state)` can reject a saved output that no longer fits the state."""
    def wrapped(state: AnalysisState, writer: StreamWriter) -> dict:
        saved = load_result(state["document_id"], key)
        if saved and saved.get("status") == "done" and (still_valid is None or still_valid(saved, state)):
            writer({"agent": name, "event": "done", "message": "reusing the result saved earlier"})
            return {key: saved}
        update = node(state, writer)
        save_result(state["document_id"], key, update[key])
        return update
    return wrapped


def parse_document(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 0, part 1: sections, risk headings and summary financials."""
    writer({"agent": "parse", "event": "started", "message": "reading the document"})
    parsed = parse_offer_document(state["file_path"], build_search_index=False)
    writer({"agent": "parse", "event": "done",
            "message": f"{parsed['page_count']} pages, {len(parsed['risks'])} risk headings"})
    return {"document_id": parsed["document_id"], "parsed": parsed}


def index_document(state: AnalysisState, writer: StreamWriter) -> dict:
    """Agent 0, part 2: the search index, unless this file already has one."""
    if state["parsed"].get("index"):
        writer({"agent": "index", "event": "done", "message": "reusing the index built earlier for this file"})
        return {}
    writer({"agent": "index", "event": "started", "message": "building the search index (a few minutes)"})
    parsed = index_offer_document(state["file_path"], state["document_id"])
    writer({"agent": "index", "event": "done",
            "message": f"{parsed['index']['chunks']} chunks in {parsed['index']['seconds']:.0f}s"})
    return {"parsed": parsed}


def score_report(state: AnalysisState, writer: StreamWriter) -> dict:
    """The rubric: Python only, so it takes no time and never varies."""
    score = score_analysis(state)
    writer({"agent": "score", "event": "done", "message": f"{score['score']:g}/100: {score['rating']}"})
    return {"score": score}


def build_graph():
    graph = StateGraph(AnalysisState)
    graph.add_node("parse", parse_document)
    graph.add_node("index", index_document)
    for name, node in (("risk", risk_agent), ("financial", financial_agent), ("legal", legal_agent),
                       ("business", business_agent), ("offer", offer_agent)):
        graph.add_node(name, reusable(name, name, node))
    graph.add_node("score", score_report)
    # A saved report explains a particular score: rewrite it if the score moved
    graph.add_node("synthesis", reusable(
        "synthesis", "report", synthesis_agent,
        still_valid=lambda saved, state: saved.get("score") == state["score"]["score"]
        and saved.get("rating") == state["score"]["rating"],
    ))

    graph.add_edge(START, "parse")
    for node in ("risk", "financial", "legal", "index"):  # fan out after parse
        graph.add_edge("parse", node)
    for node in ("business", "offer"):                    # these two need the index
        graph.add_edge("index", node)
    graph.add_edge(AGENTS, "score")  # a join: runs once all five agents are done
    graph.add_edge("score", "synthesis")
    graph.add_edge("synthesis", END)
    return graph.compile()
