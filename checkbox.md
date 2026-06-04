# Implementation Progress

## Phase 1: Database Setup

- [x] `database/schema.sql` — DDL for all 7 GST tables
- [x] `database/seed_data.py` — Synthetic GST data (50 suppliers, 200 buyers, 5K invoices, 14994 items)
- [x] `database/descriptions.json` — Column descriptions for LLM context
- [x] `database/connection.py` — SQLAlchemy engine factory
- [x] Verification: 5000 invoices, 14994 items, 464 export records confirmed

## Phase 2: Core Pipeline (LLM Integration)

- [x] `config/settings.py` — Central config with Pydantic
- [x] `config/prompts.py` — All LLM prompt templates (zero-shot + few-shot + correction)
- [x] `core/llm_client.py` — Abstract base + GroqClient + OpenRouterClient with rate limiting
- [x] `core/schema_extractor.py` — DB metadata + descriptions → context string
- [x] `core/prompt_builder.py` — Assembles system prompt + schema + question
- [x] `core/sql_generator.py` — Question → prompt → LLM → extract SQL
- [x] Verification: `SQLGenerator.generate()` tested — correct SQL for simple, multi-join, and ranking queries

## Phase 3: SQL Validation & Execution

- [x] `core/sql_validator.py` — SELECT-only enforcement via sqlparse
- [x] `core/sql_executor.py` — Run SQL, return DataFrame + metadata
- [x] `core/self_correction.py` — Error feedback loop (up to 3 attempts)
- [x] `core/pipeline.py` — End-to-end orchestrator
- [x] Verification: all 3 test queries passed; self-correction triggered and resolved on attempt 2

## Phase 4: Streamlit UI

- [ ] `ui/app.py` — Chat interface with SQL/Results/Chart tabs
- [ ] Verification: All 8 example questions work in browser

## Phase 5: Evaluation & Benchmarking

- [ ] `evaluation/test_questions.json` — 100+ gold question-SQL pairs (simple/moderate/challenging)
- [ ] `evaluation/metrics.py` — EX, VER, EM metrics
- [ ] `evaluation/benchmark.py` — Batch runner across models/configs
- [ ] `notebooks/03_evaluation_analysis.ipynb` — Results analysis
- [ ] Verification: Benchmark script produces CSV with per-question results

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
