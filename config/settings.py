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

    # ── Phase 5-B: RAG (retrieval-augmented). Baseline ignores all of these. ──
    embed_model: str = "BAAI/bge-large-en-v1.5"   # challenger: BAAI/bge-m3 (intrinsic compare)
    rag_top_k_tables: int = 5
    rag_top_k_fewshots: int = 5     # locked via Grid-B sweep (k=5 > k=3; fixed #59/#94/#109)
    rag_index_dir: str = "index"
    qsql_store_path: str = "evaluation/rag_qsql_store.json"
    rag_always_include_core_tables: bool = True   # ablation toggle, not an assumption
    rag_retrieval_mode: str = "hybrid"            # locked: "semantic" | "hybrid" (BM25+RRF); hybrid on intrinsic+robustness (ties sem on eval)
    rag_hybrid_dense_weight: float = 0.6          # used only if weighted fusion (vs RRF)
    rag_category_weight: float = 0.0              # >0 enables predicted-category rerank
    rag_embed_seed: int = 0                        # determinism
    rag_trace_path: str = "evaluation/results/rag_traces.jsonl"

    @field_validator("rag_retrieval_mode")
    @classmethod
    def validate_retrieval_mode(cls, v: str) -> str:
        if v not in {"semantic", "hybrid"}:
            raise ValueError("rag_retrieval_mode must be 'semantic' or 'hybrid'")
        return v

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