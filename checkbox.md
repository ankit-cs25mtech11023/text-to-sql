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
- [x] **Triage failures (per [[feedback_baseline_production_rigor]]) — done at 112-scale (2026-06-17).** General, non-overfit only: (1) **test-quality gold fixes** — 14 ranking golds → entity-only (minimal-projection per the EX metric spec), #62 decode→`desc_year`, #77 fixed broken filings-vs-taxpayers count (24→4), #72 boundary-tie top-5→top-4; (2) **one general prompt fact** — 3B tax payable = `iamt+camt+samt+csamt`; `*_tx`/`tax_pay` belong to GSTR-7 (fixed #68/#79). A decode-rule prose attempt was **reverted** (0 EX gain + a regression). Residuals classified as RAG/few-shot targets — see plan.md "Static-Prompt Ceiling".
- [x] Grow gold set to 100+ → **112** done (no artificial cap; broad coverage).
- [x] **Full 112-question baseline (runs=3, 2026-06-17) → EX 90.2% ± 0.0, VER 97.6% ± 0.5** (up from 86.6% pre-triage). By difficulty: simple 98.0 / moderate 89.5 / challenging 77.4. Stable across runs (flaky: #62, #110). → `evaluation/results/baseline.csv` (gitignored).

## Phase 5-B: RAG Enhancement (Branch: `rag-enhancement`)

> Branch `rag-enhancement` active. Authoritative spec: `RAG_plan.md`. Order = intrinsic-first
> (CPU variant selection), then cheap extrinsic signal, then 2×2 + ablations.

### Part A — Disjoint retrieval pool (`RAG_plan.md` §4)
- [x] Probe `gst_official` for verified columns + categorical values (decode tables, EWB/3B/GSTR-7 cols, value ranges)
- [x] Read source-of-truth files (descriptions_official.json, 3 DDLs, config/prompts.py 5 few-shots, 112 eval set)
- [x] `evaluation/rag_qsql_store.json` — **140 pairs authored** (IDs 1001–1140), stratified per §4.1 (decode 15, ranking 20, domain 24, agg 22, grouping 16, join 12, filtering 10, quirk 8, subquery 8, having 5; modules 3B 54 / EWB 45 / R7 41)
- [x] Verify every gold_sql executes on `gst_official` — **0 failures** (no error / empty / NULL); ids unique; 0 exact-dup vs eval
- [x] **Leakage audit** (`evaluation/leakage_audit.py`, §2) — two signals: (1) question cosine>0.90 = 62 (template similarity, expected on short single-domain Qs; bge-large max 0.9747); (2) **SQL template-twins (literal-masked gold-SQL identity) = 0 → PASS**. 9 borderline twins reworded to clear it. Report → `evaluation/results/leakage_audit.csv`

### Part B — Deps + components (`RAG_plan.md` §5)
- [x] Install deps: CPU-only `torch==2.12.1+cpu` (no GPU on laptop), `sentence-transformers`, `faiss-cpu`, `rank_bm25`; pinned in `requirements.txt`
- [x] gitignore `index/` (+ `results/*.jsonl` for traces)
- [x] `config/settings.py` — RAG fields (embed_model, top_k, retrieval_mode, hybrid/category weights, seed, trace_path, always_core) + retrieval_mode validator
- [x] `core/rag_retriever.py` — qsql FAISS (IndexFlatIP, question-only embed); **semantic + hybrid (BM25+RRF)** + optional predicted-category rerank; deterministic id tie-break; smoke-tested both modes. `retrieve_tables` stubbed until SchemaIndexer
- [x] `evaluation/intrinsic_eval.py` — Layer-1 CPU: same-category/module/both hit@k + MRR + latency per config; CSV per config + comparison table
- [ ] `core/schema_indexer.py` — `SchemaExtractor.get_table_blocks()` → M-Schema per table → FAISS (schema side)
- [x] `config/rag_prompts.py` (NEW, not editing prompts.py) — `RAG_SYSTEM_PROMPT_TEMPLATE` + `SHARED_HEADER` **derived** from baseline template (sliced, not duplicated) → prompts.py stays byte-identical to main; + fewshot/schema formatters
- [x] `core/rag_prompt_builder.py` (NEW) — `RAGPromptBuilder` subclass, per-question build_messages; modes fewshot/schema/both (schema/both gated until SchemaIndexer); base prompt_builder.py untouched
- [x] `core/rag_pipeline.py` (NEW) — `RAGTextToSQLPipeline` subclass (`__init__` only; `ask()` inherited); base pipeline.py untouched
- [x] `evaluation/benchmark.py` — `--rag` + `--rag-mode {fewshot,schema,both}`; **trace JSONL (#10)** (run-1) + efficiency (#9: retrieval latency, approx prompt tokens) built in
- [x] **Merge-safety verified:** `git diff main` on pipeline.py/prompt_builder.py/sql_generator.py/prompts.py = EMPTY (all RAG ships as new files + additive settings/benchmark)
- [ ] `evaluation/intrinsic_eval.py` — CPU-only recall@k / same-category hit / leakage / prompt-tokens (Layer-1, §3.5)
- [x] `core/llm_client.py` — vLLM/OpenAI client (done in Phase 2 — now the only client)

### Layer 1 — Intrinsic retrieval study (CPU, no HPC) (`RAG_plan.md` §3.5)
- [~] Embed-model compare: `bge-large` vs `bge-m3` (#1) — **bge-large done**; bge-m3 pending (2GB download)
- [x] Semantic vs hybrid (BM25+RRF, #2) — on bge-large, **hybrid wins** (same-both hit@3 81.2% vs 79.5%, MRR 0.740 vs 0.708)
- [ ] Category-aware rerank: predicted vs oracle (#7)
- [~] Pick winning retriever config → `intrinsic_*.csv` written; **leading = bge-large hybrid** (confirm vs bge-m3 before locking)

### Layer 2 — Extrinsic EX (HPC + tunnel) (`RAG_plan.md` §6, §9)
- [ ] Health-check tunnel (`curl -m5 localhost:8765/v1/models`) before any benchmark run
- [x] Few-shot RAG only (bge-large, semantic, k=3): `--rag-mode fewshot --runs 3` → `rag_fewshot.csv`. **EX 90.2%→94.6% (+4.4), VER 97.6%→100%, stable ±0.0.** decode **25%→100%** (headline residual fixed); fixed 11/12 baseline fails; regressed 5 (amt_ded name-trap #94/#96/#109, deductor/deductee #107, static-twin #59, decode-label #62) — trace-diagnosed, pool-fixable next loop
- [ ] Schema-retrieval only: `--rag-mode schema --runs 3` (2×2 cell, real run #12)
- [ ] Full RAG: `--rag-mode both --runs 3` → `rag.csv` (headline)
- [ ] Always-core on/off ablation (#6): rerun winning mode with `rag_always_include_core_tables` toggled
- [ ] **2×2 table** (Baseline / Schema-only / Few-shot-only / Full RAG) — EX/VER + by-category + by-difficulty + prompt-tokens
- [ ] Reframe hypotheses as tested (#14) — done in RAG_plan; reflect in results narrative

### Verification (`RAG_plan.md` §8)
- [ ] Retrieval sanity: decode Q → decode-join demos + 3B/`common.mst_*` tables; GSTR-7 Q → r7 tables (spot-check 3–4)
- [ ] Leakage audit passes (report saved)
- [ ] Base untouched: `git diff main -- core/pipeline.py core/prompt_builder.py core/sql_generator.py` = additions only
- [ ] Trace spot-check: a fixed residual (decode Q) shows a decode-join demo in `rag_traces.jsonl`

### Deferred (if time) (`RAG_plan.md` §9 "Deferred items")
- [ ] #4 cross-encoder reranker · #5 dynamic-k · #8 structural/AST index · #13 pool-size sweep · top-K table sweep

## Phase 6: Production Hardening (post-thesis green light)

- [ ] PostgreSQL migration
- [ ] FastAPI wrapper (`POST /query`)
- [x] `VLLMClient` for local GPU (done in Phase 2)
- [ ] Security: audit logging, rate limiting, prompt injection defense
- [ ] Hash-based query cache
