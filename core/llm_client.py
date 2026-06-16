from abc import ABC, abstractmethod

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


class VLLMClient(LLMClient):
    # Local vLLM OpenAI-compatible endpoint (SSH-tunneled HPC GPU server).
    # `openai` here is just the HTTP client for the OpenAI-compatible protocol
    # vLLM exposes — no calls leave the tunnel, nothing is billed.
    # vLLM ignores the key, but the OpenAI SDK rejects an empty string.
    def __init__(
        self,
        base_url: str = "http://localhost:8765/v1",
        model: str = "xiyansql",
        api_key: str = "EMPTY",
        timeout: float = 120.0,
        max_retries: int = 1,
    ) -> None:
        # Fail fast on a dead/flapping endpoint instead of hanging on the SDK's
        # 600s default + retries (e.g. when the SSH tunnel or HPC server drops).
        self._client = OpenAI(
            api_key=api_key or "EMPTY",
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
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
    model: str,
    base_url: str | None = None,
    api_key: str = "EMPTY",
) -> LLMClient:
    if provider == "vllm":
        return VLLMClient(
            base_url=base_url or "http://localhost:8765/v1",
            model=model,
            api_key=api_key,
        )
    raise ValueError(f"Unknown provider: {provider!r} (only 'vllm' is supported)")
