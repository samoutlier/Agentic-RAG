import json
import numpy as np
from langchain_groq import ChatGroq
from app.ingest import embedding_model, load_index
from app.config import TOP_K_RESULTS, GROQ_API_KEY, LLM_MODEL, LLM_TEMPERATURE
from app.prompt_templates import get_prompt


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
    query_embedding = embedding_model.encode(query, normalize_embeddings=True)
    query_embedding = np.array([query_embedding], dtype=np.float32)

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


# LLM Setup
llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model_name=LLM_MODEL,
    temperature=LLM_TEMPERATURE,
)


def query_document(question: str, domain: str) -> dict:
    """Full RAG query pipeline:
    1. Retrieve top-K chunks from FAISS that are most similar to the question
    2. Format those chunks into a context string with source citations
    3. Build the domain-specific prompt by injecting context + question
    4. Send the prompt to Groq LLM and get the answer
    5. Return the answer along with source chunks for citation display
    """
    chunks = retrieve_chunks(question, domain)

    if not chunks:
        return {
            "answer": "No relevant documents found for this domain. Please upload documents first.",
            "sources": [],
        }
    context = format_context(chunks)
    prompt = get_prompt(domain)
    formatted_prompt = prompt.format(context=context, question=question)

    response = llm.invoke(formatted_prompt)

    return {
        "answer": response.content,
        "sources": build_sources(chunks),
    }


async def stream_query(question: str, domain: str):
    """Streaming version of query_document.
    Yields Server-Sent Events: sources first, then tokens, then done signal.
    """
    chunks = retrieve_chunks(question, domain)

    if not chunks:
        yield f"data: {json.dumps({'type': 'error', 'content': 'No relevant documents found.'})}\n\n"
        return

    yield f"data: {json.dumps({'type': 'sources', 'content': build_sources(chunks)})}\n\n"

    context = format_context(chunks)
    prompt = get_prompt(domain)
    formatted_prompt = prompt.format(context=context, question=question)

    async for token_chunk in llm.astream(formatted_prompt):
        if token_chunk.content:
            yield f"data: {json.dumps({'type': 'token', 'content': token_chunk.content})}\n\n"

    yield f"data: {json.dumps({'type': 'done', 'content': ''})}\n\n"
