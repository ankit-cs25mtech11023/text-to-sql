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
- [x] `evaluation/rag_qsql_store.json` — **142 pairs** (IDs 1001–1142), stratified per §4.1 (decode 15, ranking 20, domain 24, agg 22, grouping 16, join 12, filtering 10, quirk 8, subquery 8, having 5; modules 3B 54 / EWB 45 / R7 43). +2 added 2026-06-25 (#1141 avg-per-deductor, #1142 per-deductor-per-deductee TDS-withheld) to fill the grouped `iamt+camt+samt` coverage hole — GENERAL, not eval-shaped (#94's literal-twin would fail the audit)
- [x] Verify every gold_sql executes on `gst_official` — **0 failures** (no error / empty / NULL); ids unique; 0 exact-dup vs eval
- [x] **Leakage audit** (`evaluation/leakage_audit.py`, §2) — two signals: (1) question cosine>0.90 = 62 (template similarity, expected on short single-domain Qs; bge-large max 0.9747); (2) **SQL template-twins (literal-masked gold-SQL identity) = 0 → PASS**. 9 borderline twins reworded to clear it. Report → `evaluation/results/leakage_audit.csv`

### Part B — Deps + components (`RAG_plan.md` §5)
- [x] Install deps: CPU-only `torch==2.12.1+cpu` (no GPU on laptop), `sentence-transformers`, `faiss-cpu`, `rank_bm25`; pinned in `requirements.txt`
- [x] gitignore `index/` (+ `results/*.jsonl` for traces)
- [x] `config/settings.py` — RAG fields (embed_model, top_k, retrieval_mode, hybrid/category weights, seed, trace_path, always_core) + retrieval_mode validator
- [x] `core/rag_retriever.py` — qsql FAISS (IndexFlatIP, question-only embed); **semantic + hybrid (BM25+RRF)** + optional predicted-category rerank; deterministic id tie-break; smoke-tested both modes. `retrieve_tables` stubbed until SchemaIndexer
- [x] `evaluation/intrinsic_eval.py` — Layer-1 CPU: same-category/module/both hit@k + MRR + latency per config; CSV per config + comparison table
- [x] `core/schema_indexer.py` — `SchemaExtractor.get_table_blocks()` → M-Schema per table → FAISS (schema side); deterministic IndexFlatIP, always-core injects 3 MAIN tables; tested end-to-end (both `schema`/`both` modes assemble + run through vLLM, valid SQL)
- [x] `config/rag_prompts.py` (NEW, not editing prompts.py) — `RAG_SYSTEM_PROMPT_TEMPLATE` + `SHARED_HEADER` **derived** from baseline template (sliced, not duplicated) → prompts.py stays byte-identical to main; + fewshot/schema formatters
- [x] `core/rag_prompt_builder.py` (NEW) — `RAGPromptBuilder` subclass, per-question build_messages; modes fewshot/schema/both (schema/both gated until SchemaIndexer); base prompt_builder.py untouched
- [x] `core/rag_pipeline.py` (NEW) — `RAGTextToSQLPipeline` subclass (`__init__` only; `ask()` inherited); base pipeline.py untouched
- [x] `evaluation/benchmark.py` — `--rag` + `--rag-mode {fewshot,schema,both}`; **trace JSONL (#10)** (run-1) + efficiency (#9: retrieval latency, approx prompt tokens) built in
- [x] **Merge-safety verified:** `git diff main` on pipeline.py/prompt_builder.py/sql_generator.py/prompts.py = EMPTY (all RAG ships as new files + additive settings/benchmark)
- [x] `evaluation/intrinsic_eval.py` — CPU-only recall@k / same-category hit / leakage / prompt-tokens (Layer-1, §3.5) — few-shot side
- [x] `evaluation/intrinsic_schema_eval.py` (NEW) — Layer-1 SCHEMA side: gold-table-coverage recall@k / full-coverage@k / decode-coverage, swept k×always-core → `intrinsic_schema_*.csv`. **k5+core-on: table-recall 98.2%, full-cover 96.4%, decode-cover 20%** (decode tables rank below top-k — documented weak spot); always-core ON > OFF on coverage
- [x] `core/llm_client.py` — vLLM/OpenAI client (done in Phase 2 — now the only client)

### Layer 1 — Intrinsic retrieval study (CPU, no HPC) (`RAG_plan.md` §3.5)
- [x] Embed-model compare: `bge-large` vs `bge-m3` (#1) — both run (`intrinsic_bge-m3_*.csv`); **~tie → bge-large kept**
- [x] Semantic vs hybrid (BM25+RRF, #2) — on bge-large, **hybrid wins** (same-both hit@3 81.2% vs 79.5%; @5 91.1% vs 86.6%, MRR 0.770 vs 0.728)
- [ ] Category-aware rerank: predicted vs oracle (#7) — **PARKED (2026-06-29)**; code exists (`rag_category_weight=0` off), study not run. Full RAG already at 98.2% without it; won't fix residuals {62,107}.
- [x] Pick winning retriever config → **bge-large + hybrid + k=5** (intrinsic recall, confirmed by Grid-B extrinsic sweep)

### Layer 2 — Extrinsic EX (HPC + tunnel) (`RAG_plan.md` §6, §9)
- [x] Health-check tunnel (`curl -m5 localhost:8765/v1/models`) before any benchmark run
- [x] `evaluation/benchmark.py` — added `--retrieval-mode {semantic,hybrid}` + `--rag-top-k N` flags (override settings per run; RAG path only; base files still byte-identical to main)
- [x] **Few-shot RAG LOCKED (hybrid, k=5, 142-pool): EX 90.2%→97.3% ±0.0, VER 97.6%→100% ±0.0** → `rag_fewshot.csv`. decode **25%→100%**. Got here via: (a) pool fix +0.9 (#109), (b) **Grid-B sweep** {sem,hyb}×{k3,k5} runs=1 screen → k=5 +1.8 (#59,#94); hyb-k3 broke #28 (k5 clean); (c) runs=3 confirm sem-k5 ≡ hyb-k5 bitwise → hybrid on intrinsic+robustness. Residuals **{62,96,107}** = findings (#96 base-vs-withheld per-deductee, #107 grouping-entity+3-table→schema cell, #62 decode-flaky). Sweep CSVs → `results/ablations/`, manifest → `results/README.md`
- [x] Schema-retrieval only: `--rag-mode schema --runs 3` → `rag_schema.csv` — **EX 86.6% ±0.0, VER 97.3%** (BELOW baseline 90.2%; retrieval drops needed tables → 6 new fails; decode stuck 25%). Clean finding: schema retrieval alone is net-negative.
- [x] Full RAG: `--rag-mode both --runs 3` → `rag.csv` (headline) — **EX 98.2% ±0.0, VER 100%**; fails {62,107}; ~8.8k tok (vs ~20.1k baseline). decode 25%→100%. Beats few-shot-only (97.3%, fixes #96).
- [x] Always-core on/off ablation (#6): `rag_both_coreoff.csv` — **EX-neutral** (98.2%, same fails {62,107}) at **~6.1k tok** vs ~8.8k. Few-shots compensate for dropped MAIN tables; core kept ON as robust default (intrinsic coverage + unseen-query guard).
- [x] **2×2 table** (Baseline 90.2 / Schema-only 86.6 / Few-shot-only 97.3 / Full RAG 98.2) — EX/VER + by-category + by-difficulty + prompt-tokens, in `results/README.md`
- [x] Reframe hypotheses as tested (#14) — done in RAG_plan; reflected in results narrative (schema-retrieval-alone hurts; few-shot is workhorse; schema pays off only with few-shots)

### Verification (`RAG_plan.md` §8)
- [x] Retrieval sanity: decode Q → decode few-shots (pool 1001–1015) + r3b table; GSTR-7 Q → r7 tables; cancelled → EWB+canceldet (spot-checked schema + few-shot sides)
- [x] Leakage audit passes (report saved → `leakage_audit.csv`, 0 SQL template-twins)
- [x] Base untouched: `git diff main` on pipeline/prompt_builder/sql_generator/prompts = EMPTY; `schema_extractor.py` = +40 additive lines (`get_table_blocks`, used only by SchemaIndexer)
- [x] Trace spot-check: decode eval ids {71,73,74,78} all retrieve decode pool demos (1001–1015) and pass EX in few-shot/full-RAG traces

### Deferred (if time) (`RAG_plan.md` §9 "Deferred items") — **PARKED (2026-06-29)**
> Assessed as unlikely to move EX past the locked 98.2% (residuals {62,107} = a flaky decode-label +
> one hard 3-table join; no retrieval knob fixes those). Kept as optional "confirms-the-choice"
> footnotes, not result-movers. Resume only if residuals become a priority or a reviewer asks.
- [ ] *(parked)* #4 cross-encoder reranker · #5 dynamic-k · #8 structural/AST index · #13 pool-size sweep · top-K table sweep · hybrid table-retrieval

## Phase 6: Production Hardening (post-thesis green light)

- [ ] PostgreSQL migration
- [ ] FastAPI wrapper (`POST /query`)
- [x] `VLLMClient` for local GPU (done in Phase 2)
- [ ] Security: audit logging, rate limiting, prompt injection defense
- [ ] Hash-based query cache
