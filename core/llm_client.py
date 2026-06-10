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
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant") -> None:
        self._client = Groq(api_key=api_key)
        self.model = model

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()


class OpenRouterClient(LLMClient):
    def __init__(self, api_key: str, model: str = "qwen/qwen3-coder:free") -> None:
        self._client = OpenAI(
            api_key=api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        self.model = model

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content.strip()


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
