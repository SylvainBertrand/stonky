"""LLM provider abstraction — swap Ollama ↔ Claude via config.

Default: Ollama with llama3.1:8b for local inference.
Claude provider is stubbed for future P2.1 activation.
"""
from __future__ import annotations

import logging
from typing import Protocol

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class LLMProvider(Protocol):
    """Interface for LLM completion providers."""

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        """Send a prompt and return the completion string."""
        ...


class OllamaProvider:
    """Local Ollama inference. Default model: llama3.1:8b."""

    def __init__(
        self,
        model: str = "llama3.1:8b",
        base_url: str = "http://localhost:11434",
    ):
        self.model = model
        self.base_url = base_url.rstrip("/")

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(f"{self.base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        return data["message"]["content"]

    async def is_available(self) -> bool:
        """Check if Ollama is running by pinging /api/tags."""
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except (httpx.ConnectError, httpx.TimeoutException):
            return False


class ClaudeProvider:
    """Anthropic Claude API. Stubbed — not active until P2.1."""

    def __init__(
        self,
        model: str = "claude-sonnet-4-20250514",
        api_key: str | None = None,
    ):
        self.model = model
        self.api_key = api_key

    async def complete(self, system: str, user: str, max_tokens: int = 1024) -> str:
        raise NotImplementedError(
            "Claude provider not yet active. Set LLM_PROVIDER=ollama."
        )


def get_provider() -> LLMProvider:
    """Factory — reads LLM settings from config. Defaults to ollama."""
    provider = settings.llm_provider.lower()
    if provider == "ollama":
        return OllamaProvider(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
        )
    elif provider == "claude":
        return ClaudeProvider(api_key=settings.anthropic_api_key)
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
