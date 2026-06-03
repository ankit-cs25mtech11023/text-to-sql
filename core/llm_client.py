import time
from abc import ABC, abstractmethod

from groq import Groq
from openai import OpenAI


class LLMClient(ABC):
    @abstractmethod
    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        pass


class GroqClient(LLMClient):
    # Free tier: 30 RPM, 6K TPM
    _MIN_INTERVAL = 2.1  # seconds between requests to stay under 30 RPM

    def __init__(self, api_key: str, model: str = "gemma2-9b-it") -> None:
        self._client = Groq(api_key=api_key)
        self.model = model
        self._last_call: float = 0.0

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        self._rate_limit()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._last_call = time.monotonic()
        return response.choices[0].message.content.strip()

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._MIN_INTERVAL:
            time.sleep(self._MIN_INTERVAL - elapsed)


class OpenRouterClient(LLMClient):
    # Free tier: ~20 RPM
    _MIN_INTERVAL = 3.1

    def __init__(self, api_key: str, model: str = "qwen/qwen3-coder:free") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = model
        self._last_call: float = 0.0

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        self._rate_limit()
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        self._last_call = time.monotonic()
        return response.choices[0].message.content.strip()

    def _rate_limit(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._MIN_INTERVAL:
            time.sleep(self._MIN_INTERVAL - elapsed)


def make_client(
    provider: str,
    api_key: str,
    model: str,
) -> LLMClient:
    if provider == "groq":
        return GroqClient(api_key=api_key, model=model)
    if provider == "openrouter":
        return OpenRouterClient(api_key=api_key, model=model)
    raise ValueError(f"Unknown provider: {provider!r}")
