import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Protocol

import httpx

from app.observability.trace import record_usage, trace_stage

_generation_timeout: ContextVar[float | None] = ContextVar("generation_timeout", default=None)


@contextmanager
def limit_generation_timeout(seconds: float | None):
    token = _generation_timeout.set(seconds)
    try:
        yield
    finally:
        _generation_timeout.reset(token)


class LLMClient(Protocol):
    def generate(self, system_prompt: str, user_prompt: str) -> str: ...


class OpenAICompatibleChatClient:
    """Minimal adapter for providers exposing an OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not api_key or not base_url or not model:
            raise ValueError("LLM_API_KEY, LLM_BASE_URL, and LLM_MODEL must all be configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def generate(self, system_prompt: str, user_prompt: str) -> str:
        limit = _generation_timeout.get()
        timeout = min(self.timeout_seconds, limit) if limit is not None else self.timeout_seconds
        if timeout <= 0:
            raise TimeoutError("model generation time budget exhausted")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        with trace_stage("llm_generation"), httpx.Client(timeout=timeout) as client:
            response = client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=payload,
            )
            response.raise_for_status()
        data = response.json()
        usage = data.get("usage") or {}
        record_usage(usage.get("prompt_tokens"), usage.get("completion_tokens"))
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise ValueError(
                f"Unexpected chat completion response: {json.dumps(data)[:500]}"
            ) from error
