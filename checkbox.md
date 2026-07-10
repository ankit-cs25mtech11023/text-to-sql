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

## Phase 7: Second-Model Comparison — Qwen3.6-27B-FP8 (Branch: `model-qwen27b`, 2026-07-08)

> Lab-hosted API (`https://api.jaypokale.me/v1`, same H100 box). **Upper-bound comparison baseline
> ONLY** (27B > 10B deploy cap). Reasoning model → needs client generalization + reasoning-output
> extraction. `main` kept clean; merge when comparison table lands. Details: `plan.md` Phase 7.

- [x] Move API key into `.env` (gitignored) + `.env.example` placeholders; gitignore `api_documentation.md` — key never committed
- [x] Probe call (2026-07-08) → WAF passes w/ browser UA; **reasoning server-separated → `content` is clean SQL** (in `message.reasoning`, not `content`/`reasoning_content`); `finish_reason=stop`; completion tokens 265 (simple) → 1646 (3-table) ⇒ **bump max_tokens ~4000**, `_extract_sql` unchanged
- [x] Context window confirmed **32768** (`/models max_model_len` + forced 400 error) = same as XiYanSQL vLLM (apples-to-apples); static prompt 26.5K + 4K output fits (30.5K < 32.7K)
- [x] `git checkout -b model-qwen27b`
- [x] `core/llm_client.py` — `default_headers` (browser UA) + accept `qwen` provider (same OpenAI-compatible VLLMClient); **context-length guard**: catch over-32K `BadRequestError` from a grown correction turn → return "" (graceful fail, no crash)
- [x] `config/settings.py` — relax `validate_provider` to {vllm,qwen}; qwen_* fields + `qwen_max_tokens`; `llm_client_kwargs()` + `effective_max_tokens()` resolvers (both pipelines use them). **Real static prompt = 28.8K Qwen tokens** (probe-measured, > 26.5K o200k est) → only ~4K output room in 32K window → `qwen_max_tokens=3000` (attempt-1 fits w/ ~1K buffer). Tight-fit hits only the 2 full-static configs (baseline, few-shot-only); retrieved-schema RAG (~12.6K real) has ample room.
- [x] `core/pipeline.py` + `core/rag_pipeline.py` — use `settings.llm_client_kwargs()` + `effective_max_tokens()` (one resolver, both providers)
- [x] `evaluation/benchmark.py` — `--provider {vllm,qwen}` flag (model_copy override)
- [x] Smoke test (provider=qwen, static baseline, real DB): 2 Qs pass end-to-end (reasoning stripped → clean SQL → count=20 ✓, IGST ✓), 1 attempt each
- [x] ~~`_extract_sql` strip reasoning~~ — **not needed**, endpoint pre-separates reasoning (probe-confirmed)
- [x] Wire `enable_thinking` as qwen-only settings toggle (`qwen_enable_thinking`, default **False**) → passed via `extra_body={"chat_template_kwargs":{"enable_thinking":...}}` in `VLLMClient`; threaded through `llm_client_kwargs()` + `make_client`; vLLM path unchanged (extra_body None). Live-confirmed: thinking-off call 0.8s, clean `SELECT 1;`
- [x] Static baseline eval (thinking-OFF, `--runs 3`) → `evaluation/results/qwen27b_baseline.csv` — **EX 92.9% ±0.0, VER 100% ±0.0** (deterministic). Beats XiYanSQL static 90.2%/97.6% (+2.7 EX). **decode 100%** (XiYan static was 25% — Qwen solves decode-JOIN natively). Weak: ranking 50% (7/14), having 0% (n=1), GSTR-7 87.5%, challenging 82.1%. ~4.7s/q
- [x] Few-shot RAG eval (thinking-OFF, hybrid k=5, `--runs 3`) → `evaluation/results/qwen27b_rag_fewshot.csv` — **EX 100% ±0.0, VER 100% ±0.0** (0 fails). vs XiYanSQL few-shot-only 97.3/100 (+2.7); baseline 92.9→100 (+7.1): ranking 50→100, having 0→100. ~20.2k tok (chars/4), retrieval 216 ms/q. ⚠ 100% on toy DB = W1 distinguishability concern (Phase 9 Tier-1).
- [x] Schema-only RAG eval (thinking-OFF, box overnight run, `--runs 3`) → `qwen27b_rag_schema.csv` — **EX 94.6% ±0.0, VER 100% ±0.0**. **ABOVE its baseline (+1.7) — opposite sign to XiYan's schema-only dip (86.6, −3.6)**: fails {25,33,38,75,97,103} = strict subset of baseline fails (fixed #108,#110 + having; broke 0). Retrieval interference = small-model phenomenon
- [x] Full RAG eval (thinking-OFF, box, `--runs 3`) → `qwen27b_rag.csv` — **EX 100% ±0.0, VER 100% ±0.0** (0 fails; ties few-shot-only). Schema-only's 6 fails all rescued by few-shots
- [x] Comparison table → `results/README.md` Phase 7 section — **all 4 Qwen cells populated** (baseline 92.9 / schema 94.6 / few-shot 100 / full RAG 100 vs XiYan 90.2/86.6/97.3/98.2). Findings: interference sign-flip (model-dependent), RAG +7.1 even at 27B, ranking = generalist's weak category (50→100 via few-shots)
- [ ] `ui/app.py` — sidebar provider/model toggle (XiYanSQL-7B vLLM ↔ Qwen3.6-27B hosted; default XiYan) — replaces hardcoded `provider="vllm"` (plan §7.6, 2026-07-11: both models are live comparison candidates; Qwen endpoint costs zero VRAM)
- [ ] Merge `model-qwen27b` → `main` (after UI toggle)

## Phase 8: New Schemas (Branch: `new-schema`, extends Phase 1)

> New govt schemas to be pasted into the branch. Pipeline is schema-agnostic — only `database/` +
> descriptions + gold/pool data change. `main` stays clean. Details: `plan.md` Phase 8.

- [ ] `git checkout -b new-schema`; paste new schema DDL → `database/Official_Schemas/`
- [ ] Extend `database/descriptions_official.json` (schema-qualified keys, LLM-HIDE)
- [ ] Seed toy data + verify counts
- [ ] Confirm `SchemaExtractor` picks up + qualifies the new schema/tables
- [ ] Grow gold eval set + RAG pool for the new module (disjoint-pool leakage discipline)
- [ ] *(if it grows)* split methodology to `SCHEMA_plan.md`

## Phase 9: Validity Hardening (review-driven, `thesis_review.md` 2026-07-02)

> External review: engineering strong, exposure = **evaluation validity**. These gate whether the
> headline (Full RAG 98.2% vs baseline 90.2%) survives an examiner. Backing spec = `thesis_review.md`
> §3–§8. Some items fold into other branches (held-out → Phase 8; ≤10B peer → model branch).

### Tier 1 — validity (gate the headline)
- [ ] **Distinguishability audit** (W1, most serious) — `evaluation/distinguishability_audit.py`: per gold, 2–3 plausible-wrong variants → execute → fraction coincidentally matching gold on toy DB; if high → adversarialize `seed_data_official.py` + re-run 2×2
- [ ] **Held-out confirmation set** (W2) — 30–40 fresh Qs, authored once, frozen configs, run once, reported unconditionally (**fold into Phase 8** new-module questions)
- [ ] **Stats** (W4) — `evaluation/stats.py`: McNemar's (paired) baseline-vs-full-RAG + Wilson 95% CIs on all headline rates; reword +0.9pp deltas as mechanism (trace of #96), not magnitude
- [ ] **Two missing ablations** (W3) — descriptions on/off; self-correction attempts 1-vs-3 (+ attempts-distribution table). Evidence 2 of 3 claimed contributions or cut them
- [ ] **Tests + 2 bug fixes** (Critical 1/2/5) — reconstruct metrics+validator unit tests into `tests/` (currently empty despite "unit-tested" claim); fix EX `permutations()` blowup (hangs on `SELECT *`) + comma-FROM allow-list bypass in `sql_validator._extract_table_names`

### Tier 2 — strengthen (if time)
- [ ] Second **≤10B SQL model** via same harness (class-of-model evidence; Qwen-27B is upper-bound only) — **fold into model branch**
- [ ] Guide spot-checks ~20 golds (inter-annotator signal, W5)
- [ ] Real tokenizer counts (replace chars/4; Qwen 28.8K measured, use actual tokenizer for XiYan)
- [ ] Paraphrase-robustness probe (10–15 paraphrases)
- [ ] NL answer-generation stage (closes "non-technical officer" goal; high demo value)

### Tier 3 — post-thesis / publication (parked)
- [ ] Benchmark release (schema clearance), schema-retrieval-interference study, self-consistency, value/cell retrieval, abstention. See `thesis_review.md` §5.10

## Phase 6-DEPLOY: IITH Portainer/H100 box (PARKED, 2026-07-08 — GPU blocker + redirected to Phase 7/8)

> Advisor-requested deploy on lab GPU server (**replaces** borrowed SLURM HPC). Access =
> Portainer web only (no SSH); shared container `iit-hyderabad`, 1× H100 NVL 95.8 GB,
> driver 575/CUDA 12.9. Our dir `/workspace/IITH_GST/Subbareddy/ankit-text2sql`.
> Full steps in `deploy_runbook.md` (local, gitignored). **BLOCKER: GPU oversubscribed
> (~91/96 GB used by mayank's 27B + giridhar's app) → serving gated on a VRAM window.**

### Done this session
- [x] Merge `rag-enhancement` → `main` (fast-forward, 0 conflicts; base files byte-identical, RAG additive/opt-in), pushed → `origin/main`
- [x] Version `evaluation/results/` as proof-of-work snapshot (baseline 90.2% / Full RAG 98.2%, CSVs + README + jsonl traces ~11 MB) — tied to code commit, non-reproducible after 4th schema
- [x] Pin thesis-figure deps (matplotlib/seaborn/pptx) in requirements.txt; gitignore local thesis docs (`report/`, `thesis_*.md`, `deploy_runbook.md`)
- [x] `deploy_runbook.md` written — secure fine-grained-PAT clone, 2-env setup, local Postgres, non-GPU/GPU steps split
- [x] Verified: nothing needed to run/test is gitignored (few-shot pool + gold set + code all tracked); only `.env`/`index/` (recreated/rebuilt) + results (now versioned) special-cased

### Non-GPU setup on box (🟢 ready — runbook §1–§6)
- [ ] Verify space (~25–30 GB free) + confirm port 8765 free
- [ ] Secure clone (fine-grained read-only PAT, no credential helper, strip after)
- [ ] Own Miniconda + `env-app` = `pip install -r requirements.txt`
- [ ] User-local Postgres cluster on 5433 + `createdb gst_official`
- [ ] `.env` from template (localhost DB + localhost vLLM)
- [ ] Seed DB + verify counts (20/63/12)

### GPU-gated (🔴 after VRAM window — runbook §7–§8)
- [ ] `env-serve` = `pip install vllm`; serve XiYanSQL-7B, **low** `--gpu-memory-utilization` (~0.25), FlashInfer/nvcc traps guarded, port 8765
- [ ] Run app (Streamlit) / RAG benchmark end-to-end on box; verify EX reproduces

## Phase 6: Production Hardening (post-thesis green light)

- [ ] PostgreSQL migration
- [ ] FastAPI wrapper (`POST /query`)
- [x] `VLLMClient` for local GPU (done in Phase 2)
- [ ] Security: audit logging, rate limiting, prompt injection defense
- [ ] Hash-based query cache
