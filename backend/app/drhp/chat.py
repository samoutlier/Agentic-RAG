"""Questions about an analysed IPO, answered with citations.

Two things go into every answer: a short summary of what the agents found
(score, flags, top risks, the offer, the promoters, the legal totals), and
passages retrieved from the document by the same hybrid search the agents
use. Passages carry their printed page numbers, so the answer can point at
them and the reader can check.

The answer streams token by token over Server-Sent Events, like the general
document chat, so it starts appearing straight away.
"""
import asyncio
import logging

import groq

from app.drhp.index import DocumentIndex
from app.drhp.parser import document_folder, load_index, load_result
from app.llm import chat_llm
from app.query import _sse, build_search_query, describe_llm_error, format_history

logger = logging.getLogger(__name__)

CHUNKS_PER_QUESTION = 6
TOP_RISKS_IN_SUMMARY = 6
# Loading an index costs about a second (FAISS file plus the BM25 word
# counts), so the last few stay in memory for follow-up questions
_indexes: dict[str, DocumentIndex] = {}
MAX_CACHED_INDEXES = 3

PROMPT = """You are answering a retail investor's questions about an Indian IPO, using only the analysis and document excerpts below.

What the analysis found:
{summary}

Excerpts from the document, each marked with its printed page:
{excerpts}

Rules:
- Answer only from the material above. If it doesn't cover the question, say so and name the section of the document to read instead.
- Cite pages like (p. 123), using the page given with that particular fact. Facts with different pages keep their own; never reuse one page for all of them, and never guess a page. A fact from the analysis that has no page gets no citation.
- Keep it to a few sentences unless more detail is asked for.
- This is educational information, never investment advice: don't tell the reader to buy, sell or subscribe.

Earlier in this conversation:
{history}

Question: {question}"""


def get_index(doc_id: str) -> DocumentIndex:
    """The document's search index, kept in memory between questions."""
    if doc_id not in _indexes:
        if len(_indexes) >= MAX_CACHED_INDEXES:
            _indexes.pop(next(iter(_indexes)))
        _indexes[doc_id] = load_index(doc_id)
    return _indexes[doc_id]


def has_analysis(doc_id: str) -> bool:
    return (document_folder(doc_id) / "analysis.json").exists()


def analysis_summary(doc_id: str) -> str:
    """What the agents found, in a few hundred tokens."""
    lines = []
    score = load_result(doc_id, "score")
    if score:
        parts = ", ".join(f"{p['label']} {p['points']:g}/{p['max_points']:g}" for p in score["parts"])
        lines.append(f"Rubric score {score['score']}/100: {score['rating']} ({score['risk_reward']['quadrant']}). {parts}.")
        lines += [f"Rating capped at Neutral: {reason}." for reason in score["knockouts"]]

    financial = load_result(doc_id, "financial") or {}
    if financial.get("scorecard"):
        lines.append("Financial scorecard: " + "; ".join(
            f"{s['dimension'].replace('_', ' ')} {s['signal']} ({s['reason']})" for s in financial["scorecard"]))
        flags = [f["message"] for f in financial.get("flags", [])]
        if flags:
            lines.append("Financial flags: " + " | ".join(flags))
    if (financial.get("assessment") or {}).get("summary"):
        lines.append("Financial summary: " + financial["assessment"]["summary"])

    risk = load_result(doc_id, "risk") or {}
    if risk.get("register"):
        counts = risk["counts"]
        lines.append(f"{counts['total']} risk factors, average score {counts['average_score']}/5.")
        top = [r for r in risk["register"] if (r["score"] or 0) >= 4][:TOP_RISKS_IN_SUMMARY]
        lines += [f"Risk {r['number']} (score {r['score']}, p. {r['page']}): {r['headline']}" for r in top]

    business = load_result(doc_id, "business") or {}
    promoters = business.get("promoters")
    if promoters:
        pledged = {True: "some shares pledged", False: "no shares pledged", None: "pledging not stated"}[
            promoters["shares_pledged"]]
        lines.append(f"Promoters: {', '.join(p['name'] for p in promoters['people'])}. "
                     f"{promoters['holding_signal']['reason']}, {pledged}.")

    offer = load_result(doc_id, "offer") or {}
    if offer.get("structure"):
        structure, metrics = offer["structure"], offer["metrics"]
        uses = "; ".join(f"{o['purpose']} ({o['amount']} {structure['amount_unit']})" for o in structure["objects"])
        lines.append(f"Offer: fresh issue {metrics.get('fresh_issue_million') or structure['fresh_issue_shares']} "
                     f"({'₹ million' if metrics.get('fresh_issue_million') else 'shares'}), "
                     f"offer for sale {structure['offer_for_sale_shares'] or 0} shares. Money for: {uses}.")
        lines += [f["message"] for f in offer.get("flags", [])]

    legal = load_result(doc_id, "legal") or {}
    if legal.get("summary"):
        summary = legal["summary"]
        cases = ", ".join(f"{kind.replace('_', ' ')} {v['count']}" for kind, v in summary["against_by_type"].items() if v["count"])
        lines.append(f"Cases against the company, promoters and directors: {cases or 'none material'}; "
                     f"claims ₹{summary['total_amount_against_million']:,.1f} m"
                     + (f" ({summary['amount_pct_of_net_worth']}% of net worth)." if summary["amount_pct_of_net_worth"] is not None else "."))

    report = load_result(doc_id, "report") or {}
    if report.get("executive_summary"):
        lines.append("Report summary: " + report["executive_summary"])
    return "\n".join(lines) if lines else "(the analysis produced nothing)"


def _sources(hits: list[dict]) -> list[dict]:
    """The citation payload the frontend shows under an answer."""
    return [
        {
            "page": hit["page"],
            "section_title": hit["section_title"],
            "text_preview": hit["text"][:200],
            "score": hit["score"],
        }
        for hit in hits
    ]


def _retrieve(doc_id: str, question: str, history: list[dict]) -> list[dict]:
    return get_index(doc_id).search(build_search_query(question, history), k=CHUNKS_PER_QUESTION)


async def stream_chat(doc_id: str, question: str, history: list[dict] | None = None):
    """Server-Sent Events: the sources used, then the answer token by token.

    Once streaming starts the HTTP status is already sent, so later failures
    arrive as an "error" event rather than an HTTP error code.
    """
    history = history or []
    try:
        # Searching embeds the question and scores every chunk: CPU work,
        # so it runs in a worker thread and leaves the server responsive
        hits = await asyncio.to_thread(_retrieve, doc_id, question, history)
        summary = await asyncio.to_thread(analysis_summary, doc_id)
    except Exception:
        logger.exception("IPO chat retrieval failed")
        yield _sse("error", "Searching the document failed. Check the backend logs for details.")
        return

    yield _sse("sources", _sources(hits))

    excerpts = "\n\n".join(f"[p. {hit['page']}] {hit['text']}" for hit in hits) or "(nothing matched the question)"
    prompt = PROMPT.format(
        summary=summary, excerpts=excerpts, history=format_history(history), question=question,
    )

    try:
        async for token in chat_llm.astream(prompt):
            if token.content:
                yield _sse("token", token.content)
    except groq.APIError as exc:
        status, message = describe_llm_error(exc)
        if status != 429:  # rate limits are expected on the free tier
            logger.exception("IPO chat streaming failed")
        yield _sse("error", message)
        return
    except Exception:
        logger.exception("IPO chat streaming failed")
        yield _sse("error", "The language model request failed. Check the backend logs for details.")
        return

    yield _sse("done", "")
