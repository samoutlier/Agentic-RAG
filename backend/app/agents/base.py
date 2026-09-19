"""What every analysis agent node shares.

    run = AgentRun("risk", RISK_AGENT_MODEL, writer)
    answer = run.ask(prompt, RiskBatch, max_output_tokens=2000)
    return {"risk": run.done(register=register)}

AgentRun sends progress messages to the UI, adds up tokens and time, and
labels the result "done" or "failed". An agent whose LLM calls fail returns
a "failed" result instead of raising, so one agent's failure doesn't stop
the others; the final report just says which part is missing.
"""
import time

import groq
from langgraph.types import StreamWriter
from pydantic import BaseModel

from app.agents.structured import AgentLLMError, ask_json

# Errors an agent survives by reporting itself failed: unusable answers
# twice, rate limits that never cleared, or Groq being unreachable
LLM_ERRORS = (AgentLLMError, groq.APIError)


class AgentRun:
    def __init__(self, name: str, model: str, writer: StreamWriter):
        self.name = name
        self.model = model
        self.writer = writer
        self.tokens = 0
        self.started = time.time()
        self.say(f"started ({model})", event="started")

    def say(self, message: str, event: str = "progress") -> None:
        """Send a progress update. During a graph run, LangGraph delivers it
        to whoever is streaming the graph with stream_mode="custom"."""
        self.writer({"agent": self.name, "event": event, "message": message})

    def ask(self, prompt: str, schema: type[BaseModel], max_output_tokens: int) -> BaseModel:
        """ask_json() on this agent's model, reporting any rate-limit waits."""
        answer, used = ask_json(
            self.model, prompt, schema, max_output_tokens,
            on_wait=lambda seconds: self.say(
                f"waiting {seconds:.0f}s for the rate limit", event="waiting"
            ),
        )
        self.tokens += used
        return answer

    def _result(self, status: str, results: dict) -> dict:
        return {
            "status": status,
            **results,
            "model": self.model,
            "tokens": self.tokens,
            "seconds": round(time.time() - self.started, 1),
        }

    def done(self, **results) -> dict:
        self.say(f"done in {time.time() - self.started:.0f}s", event="done")
        return self._result("done", results)

    def failed(self, error: Exception | str, **partial_results) -> dict:
        """A failed result, keeping anything the agent worked out without the LLM."""
        self.say(f"failed: {error}", event="failed")
        return self._result("failed", {"error": str(error), **partial_results})
