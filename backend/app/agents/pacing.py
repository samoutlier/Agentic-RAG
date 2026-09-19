"""Keeps each Groq model under its tokens-per-minute limit.

Groq's free tier allows 8,000 tokens per minute per model. Agent calls are
fast (a few seconds each), so running them one after another would still use
~16,000 tokens in under a minute and get rate-limited. Before each call the
agent asks the budget for room. If the model's calls over the last 60 seconds
leave too little, it waits until enough of those calls fall out of the window.

Some models also limit output tokens per minute (Groq's "OTPM"): the free
tier allows qwen3.8-27b only 1,000. Those are tracked the same way.
"""
import threading
import time
from collections import deque
from typing import Callable


class TokenBudget:
    def __init__(
        self,
        tokens_per_minute: int,
        output_limits: dict[str, int] | None = None,
        window_seconds: float = 60.0,
    ):
        self.tokens_per_minute = tokens_per_minute
        self.output_limits = output_limits or {}  # model -> output tokens per minute
        self.window_seconds = window_seconds
        # model -> recent calls, oldest first, as [timestamp, tokens, output tokens]
        self._calls: dict[str, deque[list]] = {}
        self._lock = threading.Lock()

    def _drop_expired(self, calls: deque, now: float) -> None:
        while calls and now - calls[0][0] >= self.window_seconds:
            calls.popleft()

    def reserve(
        self,
        model: str,
        tokens: int,
        output_tokens: int = 0,
        on_wait: Callable[[float], None] | None = None,
    ) -> list:
        """Wait until the call fits in `model`'s budget, then claim it.
        `tokens` is the call's total (prompt + reply), `output_tokens` the
        reply's maximum.

        Returns the reservation, which settle() later corrects to the real
        usage. `on_wait(seconds)` is called before each wait, so the UI can
        say "waiting for the rate limit".
        """
        output_limit = self.output_limits.get(model)
        if tokens > self.tokens_per_minute or (output_limit and output_tokens > output_limit):
            raise ValueError(
                f"A call of ~{tokens} tokens ({output_tokens} output) can never fit in "
                f"{model}'s per-minute limits; split it up."
            )
        while True:
            with self._lock:
                now = time.monotonic()
                calls = self._calls.setdefault(model, deque())
                self._drop_expired(calls, now)
                used = sum(call[1] for call in calls)
                used_output = sum(call[2] for call in calls)
                if used + tokens <= self.tokens_per_minute and (
                    not output_limit or used_output + output_tokens <= output_limit
                ):
                    reservation = [now, tokens, output_tokens]
                    calls.append(reservation)
                    return reservation
                # Wait until the oldest call leaves the window, then check again
                wait = self.window_seconds - (now - calls[0][0]) + 0.5
            if on_wait:
                on_wait(wait)
            # Sleep outside the lock, so calls to other models aren't held up
            time.sleep(wait)

    def settle(self, reservation: list, actual_tokens: int, actual_output_tokens: int | None = None) -> None:
        """Replace a reservation's estimates with what the call really used."""
        with self._lock:
            reservation[1] = actual_tokens
            if actual_output_tokens is not None:
                reservation[2] = actual_output_tokens

    def used(self, model: str) -> int:
        """Tokens `model` has used in the current window."""
        with self._lock:
            calls = self._calls.get(model, deque())
            self._drop_expired(calls, time.monotonic())
            return sum(call[1] for call in calls)
