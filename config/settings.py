from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    database_url: str = "sqlite:///database/gst_demo.db"
    descriptions_path: str = "database/descriptions.json"

    default_provider: str = "groq"
    default_model: str = "llama-3.1-8b-instant"

    temperature: float = 0.0
    max_tokens: int = 1024
    max_correction_attempts: int = 3
    query_result_limit: int = 500
    query_timeout_seconds: int = 30

    few_shot_examples: int = 0  # 0 = zero-shot; set to 3 or 5 for ablation

    # Models available per provider
    groq_models: list[str] = [
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
    ]
    openrouter_models: list[str] = [
        "qwen/qwen3-coder:free",
        "qwen/qwen3-next-80b-a3b-instruct:free",
    ]

    @field_validator("default_provider")
    @classmethod
    def validate_provider(cls, v: str) -> str:
        if v not in ("groq", "openrouter"):
            raise ValueError("default_provider must be 'groq' or 'openrouter'")
        return v

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


def get_settings() -> Settings:
    return Settings()
