import asyncio
import json
import logging

import groq
from app.ingest import embed, load_index
from app.llm import chat_llm
from app.config import TOP_K_RESULTS, HISTORY_MAX_MESSAGES, HISTORY_MAX_CHARS
from app.prompt_templates import get_prompt

logger = logging.getLogger(__name__)


def retrieve_chunks(query: str, domain: str) -> list[dict]:
    """Embed the query and retrieve the top-K most similar chunks
    from the domain's FAISS index.

    FAISS search returns (distances, indices) — distances is how far
    each result vector is from the query vector (lower = more similar),
    and indices tells us which position in our documents list it maps to.
    """
    index, documents = load_index(domain)

    # If no documents have been ingested yet, return empty
    if index.ntotal == 0:
        return []

    # Encode query into the same vector space as the stored chunks
    query_embedding = embed([query])  # shape [1, 384]

    # Ask FAISS for the top-K nearest vectors
    # Returns: distances (shape [1, K]), indices (shape [1, K])
    k = min(TOP_K_RESULTS, index.ntotal)
    distances, indices = index.search(query_embedding, k)

    chunks = []
    for i in range(len(indices[0])):
        idx = indices[0][i]
        if idx == -1:  # FAISS returns -1 for empty slots
            continue
        doc = documents[idx]
        chunks.append({
            "text": doc["text"],
            "metadata": doc["metadata"],
            "distance": float(distances[0][i]),
        })

    return chunks


def format_context(chunks: list[dict]) -> str:
    """Format retrieved chunks into a context string for the LLM prompt."""
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        meta = chunk["metadata"]
        source = f"[Source {i}: {meta.get('filename', '?')}, Page {meta.get('page', '?')}]"
        parts.append(f"{source}\n{chunk['text']}")
    return "\n\n---\n\n".join(parts)


def format_history(history: list[dict]) -> str:
    """Render recent chat messages as plain text for the prompt.

    Only the last HISTORY_MAX_MESSAGES are kept and each is trimmed to
    HISTORY_MAX_CHARS, so a long conversation can't blow through Groq's
    free-tier tokens-per-minute limit.
    """
    recent = history[-HISTORY_MAX_MESSAGES:]
    if not recent:
        return "(none, this is the first question)"

    lines = []
    for turn in recent:
        speaker = "User" if turn["role"] == "user" else "Assistant"
        text = turn["content"]
        if len(text) > HISTORY_MAX_CHARS:
            text = text[:HISTORY_MAX_CHARS] + " [...]"
        lines.append(f"{speaker}: {text}")
    return "\n\n".join(lines)


def build_search_query(question: str, history: list[dict]) -> str:
    """Text used to search FAISS for relevant chunks.

    A follow-up like "which of those is riskiest?" has almost no searchable
    meaning on its own, so the previous user question is prepended to give
    the embedding its topic. An LLM could rewrite the question instead, but
    that would double the Groq calls per question on a rate-limited free tier.
    """
    previous_questions = [turn["content"] for turn in history if turn["role"] == "user"]
    if not previous_questions:
        return question
    return f"{previous_questions[-1]}\n{question}"


def build_sources(chunks: list[dict]) -> list[dict]:
    """Shape retrieved chunks into the citation payload sent to the frontend."""
    return [
        {
            "filename": c["metadata"].get("filename", ""),
            "page": c["metadata"].get("page", 0),
            "chunk_id": c["metadata"].get("chunk_id", 0),
            "text_preview": c["text"][:200],
            "distance": c["distance"],
        }
        for c in chunks
    ]


def describe_llm_error(exc: groq.APIError) -> tuple[int, str]:
    """Turn a Groq failure into an HTTP status code and a message the user can act on."""
    if isinstance(exc, groq.RateLimitError):
        return 429, "Groq's free-tier rate limit was reached. Wait about a minute and try again."
    if isinstance(exc, groq.AuthenticationError):
        return 500, "The Groq API key was rejected. Check GROQ_API_KEY in backend/.env."
    if isinstance(exc, groq.APIConnectionError):  # includes timeouts
        return 503, "Couldn't reach Groq. Check the server's internet connection and try again."
    return 502, "The language model request failed. Check the backend logs for details."


def query_document(question: str, domain: str, history: list[dict] | None = None) -> dict:
    """Full RAG query pipeline:
    1. Retrieve top-K chunks from FAISS that are most similar to the question
       (plus the previous question, so follow-ups find the right topic)
    2. Format those chunks into a context string with source citations
    3. Build the domain-specific prompt with history, context and question
    4. Send the prompt to Groq LLM and get the answer
    5. Return the answer along with source chunks for citation display

    Groq failures are raised as groq.APIError; the API layer turns them
    into HTTP errors using describe_llm_error().
    """
    history = history or []
    chunks = retrieve_chunks(build_search_query(question, history), domain)

    if not chunks:
        return {
            "answer": "No relevant documents found for this domain. Please upload documents first.",
            "sources": [],
        }
    context = format_context(chunks)
    prompt = get_prompt(domain)
    formatted_prompt = prompt.format(
        history=format_history(history), context=context, question=question
    )

    response = chat_llm.invoke(formatted_prompt)

    return {
        "answer": response.content,
        "sources": build_sources(chunks),
    }


def _sse(event_type: str, content) -> str:
    """Format one Server-Sent Event: a `data:` line followed by a blank line."""
    return f"data: {json.dumps({'type': event_type, 'content': content})}\n\n"


async def stream_query(question: str, domain: str, history: list[dict] | None = None):
    """Streaming version of query_document.
    Yields Server-Sent Events: sources first, then tokens, then a done signal.

    Once streaming starts, the HTTP 200 status has already been sent, so a
    failure after that point can't become an HTTP error code. Errors are sent
    as an in-stream "error" event instead, which the frontend displays.
    """
    history = history or []

    try:
        # Embedding the question is CPU work; a worker thread keeps the server
        # free to handle other requests in the meantime.
        chunks = await asyncio.to_thread(
            retrieve_chunks, build_search_query(question, history), domain
        )
    except Exception:
        logger.exception("Retrieval failed")
        yield _sse("error", "Searching the documents failed. Check the backend logs for details.")
        return

    if not chunks:
        yield _sse("error", "No documents are indexed for this domain yet. Upload one first.")
        return

    yield _sse("sources", build_sources(chunks))

    context = format_context(chunks)
    prompt = get_prompt(domain)
    formatted_prompt = prompt.format(
        history=format_history(history), context=context, question=question
    )

    try:
        async for token_chunk in chat_llm.astream(formatted_prompt):
            if token_chunk.content:
                yield _sse("token", token_chunk.content)
    except groq.APIError as exc:
        status, message = describe_llm_error(exc)
        if status != 429:  # rate limits are expected on the free tier; don't log a traceback
            logger.exception("LLM streaming failed")
        yield _sse("error", message)
        return
    except Exception:
        logger.exception("LLM streaming failed")
        yield _sse("error", "The language model request failed. Check the backend logs for details.")
        return

    yield _sse("done", "")
