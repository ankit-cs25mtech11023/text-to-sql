from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql:///gst_official"
    descriptions_path: str = "database/descriptions_official.json"

    # Local-only inference. APIs (Groq/OpenRouter) were dropped: the ~26.5K-token
    # schema prompt exceeds free-tier context/TPM limits and rate caps make
    # evaluation impractical. All models are served locally via vLLM (HPC).
    default_provider: str = "vllm"
    default_model: str = "xiyansql"
    vllm_base_url: str = "http://localhost:8765/v1"
    vllm_api_key: str = "EMPTY"

    temperature: float = 0.0
    max_tokens: int = 1024
    max_correction_attempts: int = 3
    query_result_limit: int = 500
    query_timeout_seconds: int = 30

    few_shot_examples: int = 0  # 0 = zero-shot; set to 3 or 5 for ablation

    @field_validator("default_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v != "vllm":
            raise ValueError("default_provider must be 'vllm' (local-only inference)")
        return v

    # extra="ignore" so stale .env keys (old GROQ/OPENROUTER) don't break startup.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def get_settings() -> Settings:
    return Settings()