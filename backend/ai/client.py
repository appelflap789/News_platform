"""The single doorway to the Claude API: client, error messages, token accounting, refusal fallback."""

from __future__ import annotations

import json
import os
import threading

import anthropic

from .. import config
from ..jobs import JobError

# Server-side refusal fallback: if a safety classifier declines a request, Anthropic re-runs it on the
# fallback model it recommends for that refusal category. Claude Haiku 5.5 has no server-side fallback.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-fable-5"}

# USD per million tokens (input, output, cache read, cache write) - only used for the cost estimate in the UI.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00, 0.20, 5.00),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10, 2.50),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
    "claude-fable-5-1": (10.00, 50.00, 0.25, 12.50),
}


class AIError(JobError):
    """Claude could not be used; the message is written for the user."""


_client: anthropic.Anthropic | None = None
_client_key = ""
_lock = threading.Lock()


def available() -> bool:
    return bool(config.api_key() or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def client() -> anthropic.Anthropic:
    global _client, _client_key
    if not available():
        raise AIError("No Anthropic API key yet. Add one on the Settings page to use Claude.")
    with _lock:
        if _client is None or _client_key != config.api_key():
            _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
            _client_key = config.api_key()
        return _client


class Usage:
    """Token and cost totals across the calls of one job."""

    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cache_write_tokens = 0
        self.cost_usd = 0.0

    def add(self, model: str, usage) -> None:
        fresh = getattr(usage, "input_tokens", 0) or 0
        output = getattr(usage, "output_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.calls += 1
        self.input_tokens += fresh
        self.output_tokens += output
        self.cache_read_tokens += cache_read
        self.cache_write_tokens += cache_write
        price_in, price_out, price_read, price_write = PRICES.get(model, PRICES["claude-opus-5-5"])
        self.cost_usd += (
            fresh * price_in + output * price_out + cache_read * price_read + cache_write * price_write
        ) / 1_000_000

    def as_dict(self) -> dict:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens + self.cache_read_tokens + self.cache_write_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "estimated_cost_usd": round(self.cost_usd, 4),
        }


def estimated_cost(model: str, prompt_chars: int, output_tokens: int) -> float:
    """About what one request costs in USD, before it is sent. A token is taken to be three characters:
    English runs at about four, German and Dutch nearer two and a half."""
    price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])[:2]
    return (prompt_chars / 3 * price_in + output_tokens * price_out) / 1_000_000


def message(*, model: str, usage: Usage | None = None, stream: bool = False, **request):
    """Send one Messages API request and return the final message.

    `stream=True` streams under the hood (needed for long outputs so the HTTP
    connection is not held idle) and still returns the complete message.
    """
    api = client()
    extra: dict = {}
    endpoint = api.messages
    if config.get("refusal_fallback") and model in FALLBACK_MODELS:
        endpoint = api.beta.messages
        extra = {"betas": [FALLBACK_BETA], "fallbacks": "default"}
    try:
        if stream:
            with endpoint.stream(model=model, **extra, **request) as live:
                reply = live.get_final_message()
        else:
            reply = endpoint.create(model=model, **extra, **request)
    except anthropic.AuthenticationError as error:
        raise AIError("The Anthropic API key was rejected. Check it on the Settings page.") from error
    except anthropic.PermissionDeniedError as error:
        raise AIError(f"This API key is not allowed to use {model}.") from error
    except anthropic.NotFoundError as error:
        raise AIError(f"The model '{model}' was not found. Choose another on the Settings page.") from error
    except anthropic.RateLimitError as error:
        raise AIError("The Anthropic API rate limit was hit. Wait a minute and try again.") from error
    except anthropic.BadRequestError as error:
        raise AIError(f"The Claude API rejected the request: {_reason(error)}") from error
    except anthropic.APIStatusError as error:
        raise AIError(f"Claude API error {error.status_code}: {_reason(error)}") from error
    except anthropic.APIConnectionError as error:
        raise AIError("Could not reach the Anthropic API. Check the internet connection.") from error
    if usage is not None:
        usage.add(model, reply.usage)
    return reply


def _reason(error: anthropic.APIStatusError) -> str:
    """The API's own explanation, without the surrounding error envelope."""
    body = error.body if isinstance(error.body, dict) else {}
    detail = body.get("error") if isinstance(body.get("error"), dict) else {}
    return detail.get("message") or error.message


def text_of(reply) -> str:
    return "".join(block.text for block in reply.content if block.type == "text")


def require_answer(reply, task: str) -> None:
    """Raise a readable error when the model declined or ran out of room."""
    if reply.stop_reason == "refusal":
        details = getattr(reply, "stop_details", None)
        category = getattr(details, "category", None)
        raise AIError(f"Claude declined to {task}" + (f" (safety category: {category})." if category else "."))
    if reply.stop_reason == "max_tokens":
        raise AIError(f"Claude ran out of output room while trying to {task}.")


def structured(*, model: str, system: str, prompt: str, schema: dict, task: str, effort: str = "low",
               max_tokens: int = 4000, usage: Usage | None = None, stream: bool = False) -> dict:
    """One request whose answer is guaranteed to be JSON matching `schema`. `stream` as for `message`."""
    reply = message(
        model=model,
        usage=usage,
        stream=stream,
        max_tokens=max_tokens,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        messages=[{"role": "user", "content": prompt}],
    )
    require_answer(reply, task)
    try:
        return json.loads(text_of(reply))
    except json.JSONDecodeError as error:
        raise AIError(f"Claude's answer could not be read while trying to {task}.") from error
