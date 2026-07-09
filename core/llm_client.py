from abc import ABC, abstractmethod

from openai import BadRequestError, OpenAI


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
    # OpenAI-compatible client. Serves two backends over the same protocol:
    #  - local vLLM (SSH-tunneled HPC): key ignored, no headers, nothing billed;
    #  - Phase 7 hosted "qwen" endpoint: needs a real key + a browser User-Agent
    #    header (Cloudflare WAF blocks default SDK user-agents).
    # The OpenAI SDK rejects an empty api_key string, so default to "EMPTY".
    def __init__(
        self,
        base_url: str = "http://localhost:8765/v1",
        model: str = "xiyansql",
        api_key: str = "EMPTY",
        timeout: float = 120.0,
        max_retries: int = 1,
        default_headers: dict | None = None,
        extra_body: dict | None = None,
    ) -> None:
        # Fail fast on a dead/flapping endpoint instead of hanging on the SDK's
        # 600s default + retries (e.g. when the SSH tunnel or HPC server drops).
        self._client = OpenAI(
            api_key=api_key or "EMPTY",
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries,
            default_headers=default_headers,
        )
        self.model = model
        # Provider-specific passthrough (qwen: chat_template_kwargs.enable_thinking).
        # None for local vLLM so its request body is unchanged.
        self._extra_body = extra_body

    def generate(
        self,
        messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        try:
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if self._extra_body is not None:
                kwargs["extra_body"] = self._extra_body
            response = self._client.chat.completions.create(**kwargs)
        except BadRequestError as e:
            # A self-correction turn can grow the prompt past the 32K window
            # (large static schema + reasoning). Fail this attempt gracefully
            # (empty SQL -> invalid -> next attempt / graceful fail) instead of
            # crashing the whole benchmark. Re-raise anything else.
            if "maximum context length" in str(e).lower():
                return ""
            raise
        return response.choices[0].message.content.strip()


def make_client(
    provider: str,
    model: str,
    base_url: str | None = None,
    api_key: str = "EMPTY",
    default_headers: dict | None = None,
    extra_body: dict | None = None,
) -> LLMClient:
    # "vllm" (local, default) and "qwen" (Phase 7 hosted comparison baseline) are
    # both OpenAI-compatible → same client, they differ only in url/key/headers.
    if provider in {"vllm", "qwen"}:
        return VLLMClient(
            base_url=base_url or "http://localhost:8765/v1",
            model=model,
            api_key=api_key,
            default_headers=default_headers,
            extra_body=extra_body,
        )
    raise ValueError(f"Unknown provider: {provider!r} (expected 'vllm' or 'qwen')")
