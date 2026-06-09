# Implementation Progress

## Phase 1 (original — superseded): SQLite Toy Schema

> Replaced by official government schemas. Files kept for reference.

- [x] `database/schema.sql` — 7-table SQLite schema (legacy, not used)
- [x] `database/seed_data.py` — SQLite synthetic data (legacy, not used)
- [x] `database/descriptions.json` — descriptions for old schema (legacy, not used)
- [x] `database/connection.py` — SQLAlchemy engine factory (needs PostgreSQL update)

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
- [x] `core/llm_client.py` — Abstract base + GroqClient + OpenRouterClient with rate limiting
- [x] `core/schema_extractor.py` — DB metadata + descriptions → context string
- [x] `core/prompt_builder.py` — Assembles system prompt + schema + question
- [x] `core/sql_generator.py` — Question → prompt → LLM → extract SQL
- [ ] Verification: re-test with official schema queries once seed data + descriptions ready

## Phase 3: SQL Validation & Execution

- [x] `core/sql_validator.py` — SELECT-only via sqlparse; updated for official schemas: get_type() CTE-aware SELECT check, schema-qualified table extraction, CTE-name exclusion (offline-tested: few-shot + injection/DELETE/UPDATE/CTE-hiding-DELETE/hallucinated all handled)
- [x] `core/sql_executor.py` — Run SQL, return DataFrame + metadata (PostgreSQL-compatible, no change needed)
- [x] `core/self_correction.py` — Error feedback loop (up to 3 attempts)
- [x] `core/pipeline.py` — Updated: read-only PG engine, allowed_tables from SchemaExtractor (all 3 schemas, qualified + bare)
- [x] Verification (old schema): all 3 test queries passed; self-correction resolved on attempt 2
- [ ] Verification (official schema): end-to-end run — NEEDS Groq API call (pending, token-budgeted)

## Phase 4: Streamlit UI

- [x] `ui/app.py` — Chat interface with SQL/Results/Chart tabs
- [ ] Verification: All 8 example questions work in browser

## Phase 5: Evaluation & Benchmarking

- [ ] `evaluation/test_questions.json` — 100+ gold question-SQL pairs (simple/moderate/challenging)
- [ ] `evaluation/metrics.py` — EX, VER, EM metrics
- [ ] `evaluation/benchmark.py` — Batch runner with caching + resume support
- [ ] Run baseline evaluation (~130 API calls) → `evaluation/results/baseline.csv`
- [ ] Verification: Baseline CSV shows per-question EX/VER/EM scores

## Phase 5-B: RAG Enhancement (Branch: `rag-enhancement`)

> Start after Phase 5 is complete on `main`. Run: `git checkout -b rag-enhancement`

- [ ] `core/schema_indexer.py` — M-Schema builder + FAISS index (one vector per table)
- [ ] `core/rag_retriever.py` — dual FAISS retrieval (top-K tables + top-K Q-SQL pairs)
- [ ] `evaluation/rag_qsql_store.json` — 50–100 GST-specific Q-SQL pairs
- [ ] `index/` — FAISS index files (gitignored, built by schema_indexer.py)
- [ ] Update `core/prompt_builder.py` — add `RAGPromptBuilder` subclass
- [ ] Update `core/pipeline.py` — add `RAGTextToSQLPipeline` subclass
- [ ] Update `core/llm_client.py` — add `VLLMClient` for local vLLM inference
- [ ] RAG ablation experiments (Schema RAG only / Few-shot RAG only / Both / Top-K sweep)
- [ ] Verification: RAG pipeline retrieves correct tables for test questions

## Phase 6: Production Hardening (post-thesis green light)

- [ ] PostgreSQL migration
- [ ] FastAPI wrapper (`POST /query`)
- [ ] `VLLMClient` for local GPU
- [ ] Security: audit logging, rate limiting, prompt injection defense
- [ ] Hash-based query cache
