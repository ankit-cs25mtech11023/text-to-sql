# Implementation Progress

## Phase 1 (original — superseded): SQLite Toy Schema

> Replaced by official government schemas. Legacy SQLite files
> (`schema.sql`, `seed_data.py`, `descriptions.json`, `gst_demo.db`) have been
> removed from the working tree — recoverable via git history.

- [x] `database/connection.py` — SQLAlchemy engine factory (PostgreSQL; SQLite fallback retained)

## Phase 1 (redo): Official Government Schemas + PostgreSQL

- [x] `database/Official_Schemas/ewb.sql` — EWB schema received (10 tables)
- [x] `database/Official_Schemas/gstr3b_new.sql` — GSTR-3B schema received (1 partitioned table)
- [x] `database/Official_Schemas/gstr7.sql` — GSTR-7 schema received (8 tables)
- [x] `database/seed_data_official.py` — Seed PostgreSQL with toy data (EWB + GSTR-3B + GSTR-7)
- [x] Update `.env.example` — DATABASE_URL=postgresql:///gst_official
- [x] Verification: EWB=20 bills/23 items, GSTR-3B=63 returns (48 fy8+15 fy9), GSTR-7=12 returns/27 TDS/54 inv
- [x] `database/descriptions_official.json` — Column descriptions for all 21 tables (3 modules + 2 common decode tables); LLM-HIDE columns omitted; schema-qualified keys
- [x] Update `database/connection.py` — PostgreSQL engine; SQLite kept as fallback
- [x] Update `core/schema_extractor.py` — multi-schema support; descriptions-driven table list; reserved/case-sensitive identifier quoting; skips 145-col GSTR-3B from sample rows
- [ ] *(pending)* 4th schema from guide — TBD

## Phase 2: Core Pipeline (LLM Integration)

- [x] `config/settings.py` — Updated: database_url→postgresql:///gst_official, descriptions_path→descriptions_official.json
- [x] `config/prompts.py` — Rewritten for official schemas: PostgreSQL dialect, 3-module map, join paths, quoting/date/padding conventions, 5 few-shot examples (all verified to execute)
- [x] `core/llm_client.py` — Abstract `LLMClient` + `VLLMClient` (OpenAI-compatible, local vLLM). Groq/OpenRouter clients, API keys, model lists, and per-provider rate limiter **removed** — local-only inference (APIs can't fit the 26.5K-token prompt + rate limits make eval impractical)
- [x] `core/schema_extractor.py` — DB metadata + descriptions → context string
- [x] `core/prompt_builder.py` — Assembles system prompt + schema + question
- [x] `core/sql_generator.py` — Question → prompt → LLM → extract SQL
- [x] Add vLLM client to `llm_client.py` + `make_client` (`provider="vllm"`, tunneled `http://localhost:8765/v1`); `settings.py`/`pipeline.py`/`ui/app.py`/`.env.example`/`requirements.txt` updated to local-only
- [x] Verification: end-to-end SQL generation on official schemas via local vLLM — **PASSED** (2026-06-15). EWB count=20 ✅, EWB total IGST ✅, all 1-attempt/ms-fast. Accuracy finding: model confused **GSTR-7 → GSTR-3B table** (answered 8 from `live_reports.r3b_...` instead of 12 from `public.tbl_gst_rtn_r7`) — valid SQL so self-correction didn't fire; prompt/RAG target, not a pipeline bug.

## Phase 3: SQL Validation & Execution

- [x] `core/sql_validator.py` — SELECT-only via sqlparse; updated for official schemas: get_type() CTE-aware SELECT check, schema-qualified table extraction, CTE-name exclusion (offline-tested: few-shot + injection/DELETE/UPDATE/CTE-hiding-DELETE/hallucinated all handled)
- [x] `core/sql_executor.py` — Run SQL, return DataFrame + metadata (PostgreSQL-compatible, no change needed)
- [x] `core/self_correction.py` — Error feedback loop (up to 3 attempts)
- [x] `core/pipeline.py` — Updated: read-only PG engine, allowed_tables from SchemaExtractor (all 3 schemas, qualified + bare)
- [x] Wired two previously-unused settings: `query_timeout_seconds` → PostgreSQL `statement_timeout` (verified it cancels a >timeout query) and `max_tokens` → threaded settings→pipeline→`run_with_correction`→generator
- [x] Verification (old schema): all 3 test queries passed; self-correction resolved on attempt 2
- [x] Verification (official schema): end-to-end run via local vLLM — PASSED (2026-06-15); see Phase 2 verification note above
- [x] Prompt-hardening pass (general, diagnostic-driven, 2026-06-15): ran a 16-Q probe across all 3 modules; fixed **table-routing**, **aggregation-grain** (SUM+GROUP BY for multi-row-per-entity), **amount-column semantics** (TDS = iamt+camt+samt, not amt_ded), and **event-vs-state grain** — generally, not per-bug. `config/prompts.py` (HOW-TO-BUILD playbook + symmetric MAIN-table grain) and `descriptions_official.json` (point-of-selection "TRAP" warnings on amt_ded/canceldet + self-advertising on iamt/camt/samt/status). **EX 11/16 → 15/16**, fixes verified to generalize across phrasings. Residual: "were cancelled"↔`canceldet` near-exact name-collision is phrasing-sensitive and resists prose — documented motivation for few-shot/RAG (Phase 5-B).

## Infrastructure: Local vLLM Inference (HPC)

- [x] Conda env `text2sql` on lab HPC (SLURM); vLLM cu129 wheel + cu129 torch (CUDA 12.9 driver match)
- [x] Model `XGenerationLab/XiYanSQL-QwenCoder-7B-2504` downloaded to HPC HF cache (removed duplicate 2502 copies)
- [x] `vllm serve` runs — root-caused OOM to SLURM `--mem`→`ulimit -v` + CUDA UVA; fix = `--mem=128G`
- [x] Endpoint smoke-tested (`/v1/models`, `/v1/chat/completions` → valid SQL)
- [x] SSH tunnel `localhost:8765` → `slurm-comp01:8765` verified from laptop
- [x] Pipeline pointed at the endpoint (`VLLMClient` wired; default provider=`vllm`, model=`xiyansql`)

## Phase 4: Streamlit UI

- [x] `ui/app.py` — Chat interface (SQL/Results tabs, async query + Stop button)
- [x] Reworked for vLLM + official schemas (2026-06-16): replaced stale toy-schema example questions with 8 official-schema ones (EWB/GSTR-3B/GSTR-7, all verified correct), added model caption + Temperature slider
- [x] Verification (headless): `streamlit.testing.AppTest` renders clean (no exceptions; title, 8 example buttons, Show-SQL toggle, Temperature slider, model caption, chat input all present); all **8/8 sidebar example questions** pass end-to-end through live vLLM (1 attempt each, correct results)
- [x] Final visual click-through in a real browser (2026-06-16): example questions return correct results; failure path works (validator correctly blocked an `information_schema` introspection query, "Last generated SQL" shown); async thread + st.rerun polling glue confirmed working

## Phase 5: Evaluation & Benchmarking

- [x] `evaluation/metrics.py` — EX / VER / EM. EX is robust: gold = minimal projection, prediction may carry EXTRA columns (row-correlation preserved via column-tuple projection), row order ignored unless `order_matters`. Unit-tested (extra-col, row-swap, reorder, fewer-col, EM-normalize).
- [x] `evaluation/benchmark.py` — batch runner → per-question CSV + summary (overall + by difficulty + by module + **by category**) + `--runs N` for mean ± std and flaky-question detection. (No caching/resume — local inference is fast, not needed.)
- [x] `evaluation/test_questions.json` — **112** verified gold pairs (EWB 42, GSTR-3B 38, GSTR-7 32; simple 49 / moderate 35 / challenging 28; 10 categories incl. decode/quirk/having/subquery). All 112 gold SQL verified to execute on `gst_official` (no error/empty/NULL). Exercises quirks: `"InvVal"`/`"range"` quoting, string-numeric casts, `TO_DATE` VARCHAR dates, partition key, FK-naming quirk.
- [x] Baseline on XiYanSQL-7B (21-Q seed, **5 runs**) → `evaluation/results/baseline.csv` (gitignored). **EX 81.0% ± 0.0, VER 90.5% ± 0.0, EM ≈ 5%**; gradient simple 90% / moderate 100% / challenging 40%. Bitwise-stable across all 5 runs (same 4 fail each time).
- [x] Verification: CSV shows per-question EX/VER/EM/attempts/time.
- [x] Determinism check: vLLM **mostly deterministic at temp 0** (5/5 runs identical, std 0.0); one earlier one-off flip seen, so K-run mean±std is kept to *confirm* stability, not assumed.
- [ ] **Triage the 4 stable failures (per [[feedback_baseline_production_rigor]]):** #4 `cancelled`→canceldet (name-trap), #9 active-bills item JOIN (bad alias), #15 GSTR-3B decode join `fy_flag`→`mst_fy_years_t` (hallucinated `fp`), #21 invoice-level TDS (`amt_ded` trap). For each: is it fixable by a *general* (non-overfit) improvement → fix it; else RAG/few-shot target.
- [x] Grow gold set to 100+ → **112** done (no artificial cap; broad coverage).
- [ ] Run full 112-question baseline (mean±std) and triage failure patterns by category.

## Phase 5-B: RAG Enhancement (Branch: `rag-enhancement`)

> Start after Phase 5 is complete on `main`. Run: `git checkout -b rag-enhancement`

- [ ] `core/schema_indexer.py` — M-Schema builder + FAISS index (one vector per table)
- [ ] `core/rag_retriever.py` — dual FAISS retrieval (top-K tables + top-K Q-SQL pairs)
- [ ] `evaluation/rag_qsql_store.json` — 50–100 GST-specific Q-SQL pairs
- [ ] `index/` — FAISS index files (gitignored, built by schema_indexer.py)
- [ ] Update `core/prompt_builder.py` — add `RAGPromptBuilder` subclass
- [ ] Update `core/pipeline.py` — add `RAGTextToSQLPipeline` subclass
- [x] Update `core/llm_client.py` — vLLM/OpenAI client (done in Phase 2 — now the only client)
- [ ] RAG ablation experiments (Schema RAG only / Few-shot RAG only / Both / Top-K sweep)
- [ ] Verification: RAG pipeline retrieves correct tables for test questions

## Phase 6: Production Hardening (post-thesis green light)

- [ ] PostgreSQL migration
- [ ] FastAPI wrapper (`POST /query`)
- [x] `VLLMClient` for local GPU (done in Phase 2)
- [ ] Security: audit logging, rate limiting, prompt injection defense
- [ ] Hash-based query cache
