"""The one way every agent talks to an LLM: ask for JSON, check it against a
Pydantic schema, and stay inside Groq's rate limits.

    result, tokens_used = ask_json(model, prompt, RiskBatch)

Around each call:
  1. Pacing: wait until the model's token budget for the last minute has room.
  2. Rate-limit retry: if Groq still answers "too many requests", wait as
     long as it asks (its retry-after header) and try again.
  3. Validation: the reply must parse into the schema. If it doesn't, the
     model gets one more try, with the validation errors shown to it.
"""
import json
import logging
import time
from typing import Callable

import groq
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from app.agents.pacing import TokenBudget
from app.config import GROQ_API_KEY, GROQ_OUTPUT_TOKENS_PER_MINUTE, GROQ_TOKENS_PER_MINUTE

logger = logging.getLogger(__name__)

# One budget shared by every agent, tracked separately for each model
budget = TokenBudget(GROQ_TOKENS_PER_MINUTE, GROQ_OUTPUT_TOKENS_PER_MINUTE)

MAX_RATE_LIMIT_RETRIES = 3
DEFAULT_RETRY_SECONDS = 20.0


class AgentLLMError(RuntimeError):
    """The model couldn't produce a valid answer (bad JSON twice, or rate
    limits that never cleared). The pipeline records the agent as failed."""


def estimate_tokens(text: str) -> int:
    """Rough token count. English averages about 4 characters per token,
    but tokenizers split numbers into small pieces (Qwen uses one token per
    digit), so each digit counts as a token. It errs high, the safe side."""
    digits = sum(ch.isdigit() for ch in text)
    return (len(text) - digits) // 4 + digits + 1


def _compact_schema(schema: type[BaseModel]) -> str:
    """The schema as JSON, minus the "title" labels Pydantic adds to every
    field: they cost tokens and tell the model nothing new. (Only string
    titles are removed, so a field actually named "title" is kept.)"""
    def strip(node):
        if isinstance(node, dict):
            return {k: strip(v) for k, v in node.items() if not (k == "title" and isinstance(v, str))}
        if isinstance(node, list):
            return [strip(v) for v in node]
        return node
    return json.dumps(strip(schema.model_json_schema()), separators=(",", ":"))


def build_prompt(prompt: str, schema: type[BaseModel]) -> str:
    """The prompt as sent: the agent's instructions plus the schema to follow."""
    return (
        f"{prompt}\n\nReply with only a JSON object that matches this JSON schema:\n"
        f"{_compact_schema(schema)}"
    )


def call_tokens(prompt: str, schema: type[BaseModel], max_output_tokens: int) -> int:
    """The tokens ask_json() will reserve for this call. Agents use it to
    split work into calls that each fit in one minute's budget."""
    return estimate_tokens(build_prompt(prompt, schema)) + max_output_tokens


def make_llm(model: str, max_output_tokens: int) -> ChatGroq:
    extra = {
        # JSON mode: Groq guarantees the reply is syntactically valid JSON
        "response_format": {"type": "json_object"},
    }
    if model.startswith("openai/gpt-oss"):
        # These models reason before answering, and reasoning tokens count
        # against the budget. Low effort is plenty for extraction work.
        extra["reasoning_effort"] = "low"
    return ChatGroq(
        api_key=GROQ_API_KEY,
        model_name=model,
        temperature=0,
        max_tokens=max_output_tokens,
        max_retries=0,  # rate limits are retried below, with pacing
        timeout=120,
        model_kwargs=extra,
    )


def _retry_after(exc: groq.RateLimitError) -> float:
    try:
        return float(exc.response.headers.get("retry-after", DEFAULT_RETRY_SECONDS))
    except (TypeError, ValueError, AttributeError):
        return DEFAULT_RETRY_SECONDS


def _invoke_paced(
    llm,
    model: str,
    prompt: str,
    max_output_tokens: int,
    on_wait: Callable[[float], None] | None,
) -> tuple[str, int]:
    """One LLM call, paced by the budget and retried on rate limits.
    Returns (reply text, tokens used)."""
    estimate = estimate_tokens(prompt) + max_output_tokens
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        reservation = budget.reserve(model, estimate, max_output_tokens, on_wait=on_wait)
        try:
            response = llm.invoke(prompt)
        except groq.RateLimitError as exc:
            budget.settle(reservation, 0, 0)  # the call never ran, so it used nothing
            if attempt == MAX_RATE_LIMIT_RETRIES:
                raise AgentLLMError(f"{model} was still rate-limited after {attempt + 1} tries") from exc
            wait = _retry_after(exc)
            # Groq's message says which limit was hit (tokens or requests, per minute or day)
            logger.warning("Rate-limited on %s; retrying in %.0f s. %s", model, wait, str(exc)[:300])
            if on_wait:
                on_wait(wait)
            time.sleep(wait)
            continue
        usage = response.response_metadata.get("token_usage") or {}
        used = usage.get("total_tokens", estimate)
        budget.settle(reservation, used, usage.get("completion_tokens"))
        return response.content, used
    raise AgentLLMError("unreachable")  # the loop always returns or raises


def ask_json(
    model: str,
    prompt: str,
    schema: type[BaseModel],
    max_output_tokens: int = 1500,
    on_wait: Callable[[float], None] | None = None,
    llm=None,
) -> tuple[BaseModel, int]:
    """Ask `model` for a JSON answer matching `schema`.

    Returns (the parsed answer, total tokens used). `llm` can be passed in
    to reuse a client or, in tests, to substitute a fake one.
    """
    # A reply can't be longer than the model's output limit per minute
    max_output_tokens = min(max_output_tokens, GROQ_OUTPUT_TOKENS_PER_MINUTE.get(model, max_output_tokens))
    llm = llm or make_llm(model, max_output_tokens)
    full_prompt = build_prompt(prompt, schema)
    total_tokens = 0
    for attempt in range(2):  # the first try, plus one repair try
        try:
            text, used = _invoke_paced(llm, model, full_prompt, max_output_tokens, on_wait)
        except groq.BadRequestError as exc:
            # Groq's JSON mode rejects a reply that isn't valid JSON, most
            # often one cut off at max_output_tokens. Worth one more try.
            if "json_validate_failed" not in str(exc):
                raise
            error, text = exc, ""
            problem = "It wasn't valid JSON (it may have been cut off), so keep it concise."
        else:
            total_tokens += used
            try:
                return schema.model_validate_json(text), total_tokens
            except ValidationError as exc:
                error = exc
                problem = f"It didn't match the schema. Problems: {exc.errors()[:5]}"
        if attempt == 1:
            raise AgentLLMError(
                f"{model} twice failed to return JSON matching {schema.__name__}"
            ) from error
        logger.warning("%s reply was unusable for %s; asking again. %s", model, schema.__name__, problem[:300])
        previous = f"Your previous reply was:\n{text[:2000]}\n\n" if text else "Your previous reply was unusable. "
        full_prompt = f"{full_prompt}\n\n{previous}{problem}\nReply again with a corrected JSON object only."
    raise AgentLLMError("unreachable")
