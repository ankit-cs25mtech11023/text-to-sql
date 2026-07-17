from pydantic import field_validator
from pydantic_settings import BaseSettings

# Cloudflare WAF fronting the Qwen endpoint blocks default SDK user-agents;
# every request must masquerade as a browser or the connection is refused.
_BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class Settings(BaseSettings):
    database_url: str = "postgresql:///gst_official"
    descriptions_path: str = "database/descriptions_official.json"

    # Primary path is local vLLM (HPC). Groq/OpenRouter were dropped (26.5K prompt
    # can't fit free tiers). Phase 7 re-adds ONE hosted provider, "qwen": a
    # lab-hosted OpenAI-compatible endpoint on the same H100 box, used only as an
    # upper-bound comparison baseline (27B > 10B deploy cap). vLLM stays the default.
    default_provider: str = "vllm"                 # "vllm" | "qwen"
    default_model: str = "xiyansql"
    vllm_base_url: str = "http://localhost:8765/v1"
    vllm_api_key: str = "EMPTY"

    # Phase 7 — Qwen3.6-27B-FP8 hosted API (key/url/model come from .env).
    qwen_base_url: str = "https://api.jaypokale.me/v1"
    qwen_api_key: str = "EMPTY"
    qwen_model: str = "Qwen/Qwen3.6-27B-FP8"
    # Reasoning model in a 32K window with a big static prompt is TIGHT. v2 (39-table
    # normalized schema) measured the full static prompt at 30.5K real Qwen tokens
    # (up from v1's 28.8K — the added GSTREG module + 17-table 3B DDL/descriptions
    # outweigh the smaller MV), leaving only ~2.2K room (32768 window).
    #   budget: prompt + max_tokens <= 32768  ->  demos + max_tokens <= 2193.
    # 1500 (earlier value) left only 693 tok of demo room, so the FEW-SHOT config
    # (static schema + retrieved demos) overflowed on GSTR-3B questions — the
    # normalized 3B demos are the longest (worst-case 5-demo block ~1361 Qwen tok),
    # tipping past 32768 -> server 400 -> VLLMClient returns "" -> 21 empty-SQL fails.
    # Thinking-OFF output is tiny (longest gold SQL = 238 tok), so 1500 was mostly
    # wasted headroom. 500 gives 2x output margin AND 1693 tok of demo room (clears
    # the 1361 worst-case with ~330 slack). Changes zero already-fitting answers;
    # only rescues the force-empties. Over-length correction turns still caught
    # gracefully in VLLMClient. (Baseline/full-RAG never overflowed; 500 harmless there.)
    qwen_max_tokens: int = 500
    # Qwen3.6 is a reasoning model (~30s/call). The server honors
    # extra_body={"chat_template_kwargs":{"enable_thinking":False}} to fully
    # disable thinking → ~24x faster (30.9s→1.3s), 65-tok output, SQL still
    # correct. Default OFF for a cheap laptop eval (deploy-style config); flip
    # ON for the quality-ceiling run. Only the qwen provider uses this.
    qwen_enable_thinking: bool = False

    temperature: float = 0.0
    max_tokens: int = 1024
    max_correction_attempts: int = 3
    query_result_limit: int = 500
    query_timeout_seconds: int = 30

    few_shot_examples: int = 0  # 0 = zero-shot; set to 3 or 5 for ablation

    # ── Phase 5-B: RAG (retrieval-augmented). Baseline ignores all of these. ──
    embed_model: str = "BAAI/bge-large-en-v1.5"   # challenger: BAAI/bge-m3 (intrinsic compare)
    rag_top_k_tables: int = 6       # v2 fix: k=6 catches rank-6 sibling-crowded leaves (#68-class); intrinsic full-cover 98.3% (k5 97.7)
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
        if v not in {"vllm", "qwen"}:
            raise ValueError("default_provider must be 'vllm' or 'qwen'")
        return v

    def llm_client_kwargs(self) -> dict:
        """Provider-appropriate args for make_client (one place both pipelines use)."""
        if self.default_provider == "qwen":
            return {
                "provider": "qwen",
                "model": self.qwen_model,
                "base_url": self.qwen_base_url,
                "api_key": self.qwen_api_key,
                "default_headers": {"User-Agent": _BROWSER_UA},
                "extra_body": {
                    "chat_template_kwargs": {
                        "enable_thinking": self.qwen_enable_thinking
                    }
                },
            }
        return {
            "provider": "vllm",
            "model": self.default_model,
            "base_url": self.vllm_base_url,
            "api_key": self.vllm_api_key,
            "default_headers": None,
            "extra_body": None,
        }

    def effective_max_tokens(self) -> int:
        """Qwen (reasoning) needs a bigger completion budget than the 7B."""
        return self.qwen_max_tokens if self.default_provider == "qwen" else self.max_tokens

    # extra="ignore" so stale .env keys (old GROQ/OPENROUTER) don't break startup.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


def get_settings() -> Settings:
    return Settings()