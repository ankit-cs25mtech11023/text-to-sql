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
    _RPM_LIMIT = 30
    _TPM_LIMIT = 6000
    _WINDOW = 60.0
    _MIN_INTERVAL = _WINDOW / _RPM_LIMIT  # 2.0s

    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant") -> None:
        self._client = Groq(api_key=api_key)
        self.model = model
        self._last_call: float = 0.0
        self._token_log: list[tuple[float, int]] = []  # (timestamp, tokens_used)

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        self._wait(messages, max_tokens)
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        now = time.monotonic()
        self._last_call = now
        used = response.usage.total_tokens if response.usage else max_tokens
        self._token_log.append((now, used))
        return response.choices[0].message.content.strip()

    def _wait(self, messages: list[dict], max_tokens: int) -> None:
        # RPM: enforce minimum gap between calls
        elapsed = time.monotonic() - self._last_call
        if elapsed < self._MIN_INTERVAL:
            time.sleep(self._MIN_INTERVAL - elapsed)

        # TPM: estimate tokens for the upcoming call and sleep until there is capacity
        est = sum(len(m.get("content", "")) for m in messages) // 4 + max_tokens
        while True:
            now = time.monotonic()
            cutoff = now - self._WINDOW
            self._token_log = [(t, tok) for t, tok in self._token_log if t > cutoff]
            if sum(tok for _, tok in self._token_log) + est <= self._TPM_LIMIT:
                break
            # Sleep until the oldest logged call exits the 60s window
            sleep_for = self._token_log[0][0] + self._WINDOW - now + 0.5
            time.sleep(max(sleep_for, 1.0))


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
