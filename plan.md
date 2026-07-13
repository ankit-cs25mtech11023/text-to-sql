# Text-to-SQL Pipeline for GST Data — Implementation Plan

## Context

Thesis project: build a Text-to-SQL pipeline that converts natural language questions about GST (Goods and Services Tax) transaction data into SQL, executes it, and shows results. The advisor's pipeline is: **NLP input → LLM (+ schema/datatypes/descriptions) → SQL command → Execute → Show results**.

**Key constraints:** open-source LLM ≤10B params (future GPU can only handle this size), PostgreSQL (official govt schemas), Streamlit frontend. Fraud detection on the whiteboard is a different student's thesis — not in our scope. One larger model (70B) included only as upper-bound baseline for thesis comparison — not a deployment candidate.

**Inference path (current):** Local vLLM serving `XGenerationLab/XiYanSQL-QwenCoder-7B-2504` on the lab HPC (SLURM GPU node) is the **only** inference path. Hosted APIs (Groq, OpenRouter) were **dropped entirely** — the ~26.5K-token static schema prompt exceeds their free-tier context/TPM limits (Groq 6K TPM), and the rate caps make a full evaluation impractical, so they aren't worth the engineering time. Any additional comparison baselines will also be **local** SQL-specialist models (≤10B) served via vLLM. This pulls the local-GPU work forward from Phase 6; see the HPC serving recipe in `CLAUDE.md`.

---

## Project Structure

```
Dev/
├── .env.example / .env              # VLLM_BASE_URL, DB URL
├── .gitignore
├── requirements.txt
├── config/
│   ├── settings.py                  # Central config (model, DB URL, limits)
│   └── prompts.py                   # All prompt templates
├── database/
│   ├── Official_Schemas/            # Official govt PostgreSQL DDL (EWB, GSTR-3B, GSTR-7)
│   ├── seed_data_official.py        # Seeds PostgreSQL with toy data for all modules
│   ├── descriptions_official.json   # Column-level descriptions for LLM context
│   └── connection.py                # SQLAlchemy engine factory
├── core/
│   ├── schema_extractor.py          # Reads DB metadata + descriptions.json → context string
│   ├── prompt_builder.py            # Assembles system prompt + schema + question
│   ├── llm_client.py                # Abstract LLM base + VLLMClient (local vLLM)
│   ├── sql_generator.py             # Question → prompt → LLM → extract SQL
│   ├── sql_validator.py             # Safety: SELECT-only, block DDL/DML via sqlparse
│   ├── sql_executor.py              # Run SQL, return DataFrame or error
│   ├── self_correction.py           # Error → LLM → retry (up to 3 attempts)
│   └── pipeline.py                  # End-to-end orchestrator
├── ui/
│   └── app.py                       # Streamlit chat interface
├── evaluation/
│   ├── test_questions.json           # 100+ gold question-SQL pairs
│   ├── benchmark.py                  # Batch runner across models/configs
│   └── metrics.py                    # Execution accuracy, valid rate, exact match
├── notebooks/
│   ├── 01_exploration.ipynb
│   ├── 02_prompt_engineering.ipynb
│   └── 03_evaluation_analysis.ipynb
└── tests/
    └── test_*.py
```

---

## Phase 1: Database Setup

**Goal:** Create a PostgreSQL database using the official government GST schemas provided by the guide, and seed it with realistic toy data for development and testing.

**Status:** ✅ Complete (3 of 4 modules) — schemas seeded, descriptions written, `SchemaExtractor` made multi-schema. 4th module pending from guide.

### Official Schemas (provided by guide)

Three modules are available now; a 4th will be provided later.

| Module | File | Tables | Description |
|--------|------|--------|-------------|
| EWB | `database/Official_Schemas/ewb.sql` | 10 | E-Way Bill — Part-A (bill + items) and Part-B (vehicle/cancel/extend/reject events) |
| GSTR-3B | `database/Official_Schemas/gstr3b_new.sql` | 1 (partitioned) | Monthly summary return — single denormalized flat table, partitioned by FY |
| GSTR-7 | `database/Official_Schemas/gstr7.sql` | 8 | TDS return — deductor/deductee TDS, invoice detail, amendments, tax payable/paid |
| *(4th)* | TBD | TBD | To be provided by guide |

### EWB Module (10 tables — `public` schema)

**Part-A tree** (the bill itself):
- `tbl_ewb_parta` — batch parent (per state/period)
- `tbl_ewb_parta_ewb` — MAIN: one row per e-way bill (frgstin, togstin, ewbno, values, status)
- `tbl_ewb_parta_ewb_itemlist` — item lines within each bill (HSN, qty, rates)

**Part-B tree** (events on the bill):
- `tbl_ewb_partb` — batch parent
- `tbl_ewb_partb_ewb` — MAIN Part-B: one row per EWB event packet (ewb_no, fin_valid_dt)
- `tbl_ewb_partb_ewb_partbdet` — vehicle / transporter update details
- `tbl_ewb_partb_ewb_canceldet` — cancellation events
- `tbl_ewb_partb_ewb_extenddet` — validity extension events
- `tbl_ewb_partb_ewb_rejdtl` — rejection events
- `tbl_ewb_partb_ewb_transdet` — transporter assignment / change events

**Cross-module bridge:** `tbl_ewb_parta_ewb.ewbno = tbl_ewb_partb_ewb.ewb_no` (logical, no enforced FK).

**LLM-HIDE columns** (exclude from prompt context): `usertyp`, `cessnonadvolval`, `cessadvol`, `cessnonadvol`, `ssupdesc` (usually blank), denormalized `ewb_no` fields in Part-B child tables.

### GSTR-3B Module (1 table — `live_reports` schema)

Single denormalized materialized view: `live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned`

- One row per `(gstin, ret_period)` — one row per filed GSTR-3B return
- Partition key: `fy_flag` (1=FY2017-18 … 11=FY2027-28) — always include in WHERE
- ~145 columns covering: geo (division/range/unit), taxpayer master, outward supplies (3.1a–e), ITC available/reversed/net (Sec 4), payments (Sec 6.1), RCM breakup, ECO supplies, `state_income` KPI
- Decode joins: `common.mst_fy_years_t` (fy_flag → "2024-25"), `common.mst_3bd_months_t` (ret_period → month name/quarter)

### GSTR-7 Module (8 tables — `public` schema)

Filed by deductors (govt depts, PSUs) who withhold GST-TDS from supplier payments.

- `tbl_gst_rtn_r7` — MAIN: gstin (deductor) + fp (return period). One row per filed return.
- `tbl_gst_rtn_r7_tds` — TDS deductee-wise totals (gstin_ded, amt_ded, iamt/camt/samt)
- `tbl_gst_rtn_r7_tds_inv` — TDS invoice-level breakdown
- `tbl_gst_rtn_r7_tdsa` — TDS amendments (original `o*` + revised values)
- `tbl_gst_rtn_r7_tdsa_inv` — TDSA invoice-level breakdown
- `tbl_gst_rtn_r7_tax_pay` — Tax payable (declared liability)
- `tbl_gst_rtn_r7_tax_paid` — Join table for settlements
- `tbl_gst_rtn_r7_tax_paid_pd_by_cash` — Tax actually paid via cash ledger

**Key quirk:** FK columns to main table are named `tbl_gst_rtn_r7` (no `id` prefix) — source DB naming anomaly.

### Important Schema Conventions

- **Dates stored as strings:** EWB and GSTR-7 dates are VARCHAR in `DD/MM/YYYY HH:MM:SS AM/PM` or `DD-MM-YYYY` format — use `TO_DATE()` or string comparisons, not direct DATE operations.
- **Padded strings:** `ssuptyp`, `transmode`, `updid` often have trailing spaces — use `TRIM()` or `LIKE` not `=`.
- **Case-sensitive columns:** `"InvVal"` and `"QtyUqc"` in EWB must be double-quoted in SQL.
- **`range` keyword:** `range` column in GSTR-3B must be double-quoted (`"range"`) — PostgreSQL reserved word.
- **`current_date` column:** Must be double-quoted (`"current_date"`) — PostgreSQL reserved function.
- **GSTR-3B partition:** Always include `fy_flag = N` in WHERE for partitioned table scans.

### Seed Data Strategy

`database/seed_data_official.py` generates toy data for all 3 modules:

**EWB:** ~3 Part-A batches, ~20 e-way bills (mix of intra-state CGST/SGST and inter-state IGST), ~40 item lines, ~15 Part-B events (vehicles, 3 cancellations, 2 extensions, 1 rejection, 2 transporter changes)

**GSTR-3B:** ~10 Gujarat taxpayers × 8 months = ~80 rows across fy_flag=8 (FY2024-25) and fy_flag=9 (FY2025-26); includes `common.mst_fy_years_t` and `common.mst_3bd_months_t` decode tables

**GSTR-7:** ~4 deductors × 3 periods = ~12 returns, ~25 TDS rows, ~50 TDS invoice rows, ~5 amendments, tax payable and paid records

### Column Descriptions (`database/descriptions_official.json`)

Will replace `descriptions.json`. Structure follows existing format but covers all 3 modules. LLM-HIDE columns are omitted. Complex columns (like `fy_flag`, `ret_period`, padded strings) get explicit LLM guidance in descriptions.

### Files to Create
- `database/seed_data_official.py` — PostgreSQL seed script for all 3 modules ✅
- `database/descriptions_official.json` — Column descriptions for LLM context (all 21 tables) ✅
- Update `database/connection.py` — support PostgreSQL via `DATABASE_URL` ✅

### Known Blocker: SchemaExtractor is single-schema
`core/schema_extractor.py` uses `inspector.get_table_names()` which only returns the **`public`** schema by default. The official schemas span **three** schemas (`public`, `live_reports`, `common`), and the LLM must emit **schema-qualified** table names (e.g. `live_reports.r3b_...`). Before the pipeline can run on the new schemas, `SchemaExtractor` must:
1. Iterate all three schemas via `inspector.get_table_names(schema=...)` and `get_schema_names()`
2. Emit schema-qualified names in DDL, descriptions, and sample-row blocks
3. Quote reserved/case-sensitive identifiers (`"range"`, `"current_date"`, `"InvVal"`, `"QtyUqc"`) in generated DDL and sample-row SELECTs
The `descriptions_official.json` keys are already schema-qualified, so the descriptions block is ready; only the live-inspection paths (DDL + sample rows) need the multi-schema fix.

### Libraries
- `psycopg2-binary` (PostgreSQL driver)
- `sqlalchemy` (already installed)
- `Faker` (already installed)

### Verification
```bash
# After running seed_data_official.py:
psql gst_official -c "SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb;"  -- expect ~20
psql gst_official -c "SELECT COUNT(*) FROM live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned;"  -- expect ~80
psql gst_official -c "SELECT COUNT(*) FROM public.tbl_gst_rtn_r7;"  -- expect ~12
```

### Legacy Files (removed)
The original toy-schema files (`database/schema.sql`, `database/seed_data.py`,
`database/descriptions.json`, `database/gst_demo.db`) have been removed from the
working tree, superseded by the PostgreSQL official schemas. They remain
recoverable via git history if ever needed.

---

## Phase 2: Core Pipeline (LLM Integration + Prompt Engineering)

**Goal:** NL question → LLM → SQL string.

### 2A. LLM Client (`core/llm_client.py`)

Abstract base class with a single local provider. vLLM exposes an OpenAI-compatible API, so the client is a thin wrapper over the `openai` SDK — just a `base_url` pointed at the SSH-tunneled HPC endpoint (no requests leave the tunnel, nothing is billed).

```python
class LLMClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024) -> str:
        pass

class VLLMClient(LLMClient): ...  # OpenAI-compatible, base_url=http://localhost:8765/v1

def make_client(provider, model, base_url=None, api_key="EMPTY") -> LLMClient:
    # only provider="vllm" is supported
```

**Hosted APIs dropped.** Groq and OpenRouter (and their `GroqClient`/`OpenRouterClient` classes, API keys, and per-provider rate limiter) were **removed**. Reason: the ~26.5K-token schema prompt exceeds free-tier context/TPM limits (Groq 6K TPM) and the rate caps make evaluation impractical. Adding a model now means downloading it to the HPC and serving it via vLLM — no new client code, just a new `--served-model-name`.

**Models for comparison (all local via vLLM, ≤10B for deployment):**

| Model | Params | Serving | Notes |
|-------|--------|---------|-------|
| `XiYanSQL-QwenCoder-7B-2504` | 7B | Local vLLM (HPC) | **Primary — serving.** Specialized SQL fine-tune (SQLite/PostgreSQL/MySQL), SOTA-class on BIRD |
| *(optional, if time permits)* other specialised SQL models | ≤10B | Local vLLM (HPC) | Additional local baselines, served identically |

**Rate limiting:** Not needed — local serving has no provider rate limits. (The earlier per-provider sleep limiter was removed.)

### 2B. Schema Extractor (`core/schema_extractor.py`)

```python
class SchemaExtractor:
    def get_ddl(self) -> str                    # CREATE TABLE statements
    def get_sample_rows(self, table, n=3) -> str # Example rows for grounding
    def get_column_descriptions(self) -> str     # From descriptions.json
    def get_full_context(self) -> dict[str, str] # Combined context block
```

Reads DB schema via `sqlalchemy.inspect` **once at pipeline init** — result is passed to `PromptBuilder` which caches the assembled system prompt. No DB reads happen per query. The schema for this project is fixed; live inspection just means a restart picks up any schema change automatically.

### 2C. Prompt Builder (`core/prompt_builder.py`)

Prompt template structure:
```
SYSTEM: You are a SQL expert for Indian GST databases.
Given a natural language question, generate a single valid SQL query.

Rules (see `config/prompts.py` for the live, authoritative copy):
- Output ONLY the SQL query, no explanations
- Use only SELECT statements; standard PostgreSQL dialect
- Schema-qualify every table (e.g. `public.tbl_ewb_parta_ewb`, `live_reports.r3b_...`)
- For intra-state: use CGST + SGST. For inter-state: use IGST
- Honour the official-schema conventions: VARCHAR dates need `TO_DATE()`, padded strings need `TRIM()`/`LIKE`, reserved/case-sensitive identifiers (`"range"`, `"current_date"`, `"InvVal"`, `"QtyUqc"`) must be double-quoted, and partitioned GSTR-3B scans must include `fy_flag = N`
- Qualify ambiguous columns with table aliases

DATABASE SCHEMA:
{ddl_statements}

COLUMN DESCRIPTIONS:
{column_descriptions}

SAMPLE DATA:
{sample_rows}

USER: {question}
```

**Start zero-shot.** Few-shot configurable for ablation in Phase 5.

**Prompt structure (beyond rules):** System prompt includes four explicit sections before the DDL — TABLE RESPONSIBILITIES (what each table stores), COLUMN OWNERSHIP (which table each key column belongs to), FOREIGN KEY RELATIONSHIPS, and COMMON JOIN PATTERNS. This was added after observing that 8B models consistently misattribute tax columns (cgst_amount etc.) to `invoices` instead of `invoice_items`, causing 3-attempt failures. The explicit mapping generalises across all query types, not just tax queries.

**Token behavior:** The chat API is stateless — every call must include the full context. The system prompt (~26.5K tokens with the official schemas) is sent with every query; there is no "send once" mechanism. vLLM mitigates this with **automatic prefix caching** (enabled by default): identical system-prompt prefixes are cached in the KV cache server-side, so repeated calls with the same schema context skip recompute of the shared prefix. For the Streamlit UI, conversation history is accumulated across turns (system sent once, then user/assistant pairs grow) so within a chat session the schema is not re-sent redundantly.

### 2D. SQL Generator (`core/sql_generator.py`)

```python
class SQLGenerator:
    def generate(self, question: str) -> str
    def _extract_sql(self, llm_response: str) -> str  # Parse from markdown blocks, strip explanations
```

### Files to Create
- `core/llm_client.py`
- `core/schema_extractor.py`
- `core/prompt_builder.py`
- `core/sql_generator.py`
- `config/prompts.py`
- `config/settings.py`

### Libraries
- `openai` (HTTP client for the vLLM OpenAI-compatible endpoint)
- `sqlalchemy`
- `python-dotenv`
- `pydantic`

### Verification
```python
from core.sql_generator import SQLGenerator
sql = generator.generate("How many e-way bills are there?")
print(sql)  # e.g. SELECT COUNT(*) FROM public.tbl_ewb_parta_ewb
```

---

## Phase 3: SQL Validation & Execution

**Goal:** Validate SQL for safety, execute it, handle errors with self-correction.

### 3A. SQL Validator (`core/sql_validator.py`)

Uses `sqlparse` for proper tokenization (not regex — avoids false positives on column names like `update_date`).

**Validation steps:**
1. Empty check
2. Keyword blocklist: INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, GRANT, REVOKE, PRAGMA
3. Single statement only (block `; DROP TABLE` injection)
4. First token must be SELECT or WITH (for CTEs)
5. Optional: verify referenced tables exist in schema

### 3B. SQL Executor (`core/sql_executor.py`)

```python
class SQLExecutor:
    def execute(self, sql: str) -> ExecutionResult
    # Returns: success, data (DataFrame), error, row_count, execution_time_ms
```

- Auto-append `LIMIT 500` if no LIMIT present
- Query timeout: 30s
- PostgreSQL engine opened read-only (`default_transaction_read_only=on`)

### 3C. Self-Correction (`core/self_correction.py`)

Up to 3 attempts per question:
1. Generate SQL
2. Validate → if invalid, feed error to LLM: "SQL rejected because: {error}. Fix it."
3. Execute → if fails, feed DB error to LLM: "SQL failed with: {db_error}. Fix it."
4. If succeeds → return results
5. After 3 failures → return error to user

**Thesis metric:** Track attempt count per query. Measures value of self-correction.

### 3D. Pipeline (`core/pipeline.py`)

```python
class TextToSQLPipeline:
    def __init__(self, config: Settings):
        # Wire together: schema_extractor, llm_client, prompt_builder,
        # sql_generator, sql_validator, sql_executor, self_corrector

    def ask(self, question: str) -> PipelineResult:
        # Single entry point for UI and evaluation
```

### Files to Create
- `core/sql_validator.py`
- `core/sql_executor.py`
- `core/self_correction.py`
- `core/pipeline.py`

### Libraries
- `sqlparse`
- `pandas`

### Verification
```python
result = pipeline.ask("What is the total tax collected by each state?")
print(result.sql)   # Valid SELECT with JOINs and GROUP BY
print(result.data)  # DataFrame with state names and tax totals
```

---

## Phase 4: Streamlit UI

**Goal:** Chat-based demo interface.

### Layout
```
+--------------------------------------------------+
|  GST Text-to-SQL Assistant              [Settings]|
+--------------------------------------------------+
|  Sidebar:                                         |
|  - Model selector (dropdown)                      |
|  - Temperature slider (0.0 - 1.0)                 |
|  - Show SQL toggle                                |
|  - Example questions (clickable)                  |
+--------------------------------------------------+
|  Chat area (st.chat_message):                      |
|                                                    |
|  User: Total IGST from exports in March 2026?     |
|                                                    |
|  Assistant:                                        |
|  [SQL tab] SELECT SUM(ii.igst_amount) ...          |
|  [Results tab] | total_igst | 4,523,891.50 |      |
|  Execution time: 45ms | Attempts: 1               |
+--------------------------------------------------+
|  Type your question...                    [Send]   |
+--------------------------------------------------+
```

### Key Implementation Details
- `st.chat_input` + `st.chat_message` for chat UX
- `@st.cache_resource` for pipeline init (expensive)
- `st.session_state` for chat history
- Response in tabs: SQL | Results
- Sidebar example questions (clickable; official-schema, all verified correct on `gst_official`):
  - "How many e-way bills are there?"
  - "What is the total IGST collected on inter-state e-way bills?"
  - "Which 3 HSN codes have the highest total assessable amount?"
  - "How many GSTR-3B returns were filed?"
  - "List the top 5 taxpayers by outward taxable value in FY 2025-26."
  - "What is the total state income for financial year 2024-25?"
  - "How many GSTR-7 returns have been filed?"
  - "What is the total TDS deducted across all GSTR-7 returns?"

### Files to Create
- `ui/app.py`

### Libraries
- `streamlit` (>=1.35)

### Verification
```bash
streamlit run ui/app.py
# Test all 8 example questions in the browser
```

---

## Phase 5: Evaluation & Benchmarking (Thesis)

**Goal:** Systematic accuracy measurement for thesis results chapter.

### 5A. Test Dataset (`evaluation/test_questions.json`)

100+ gold question-SQL pairs:
- **Simple** (40 questions): Single table, basic WHERE/GROUP BY
- **Moderate** (35 questions): 2-table JOIN, subqueries, date filtering
- **Challenging** (25 questions): 3+ table JOIN, nested subqueries, HAVING, GST domain knowledge

**Categories:** aggregation, filtering, ranking, time_series, comparison, domain_specific

### 5B. Metrics (`evaluation/metrics.py`)

| Metric | Description |
|--------|-------------|
| **Execution Accuracy (EX)** | Primary — does generated SQL produce same results as gold SQL? |
| **Valid Execution Rate (VER)** | Does SQL run without error? |
| **Exact Set Match (EM)** | Strict SQL comparison after normalization |

### 5C. Evaluation Strategy

**Active (run now):** Single baseline run only.

| Run | Config | Purpose |
|-----|--------|---------|
| Baseline | XiYanSQL-7B (local vLLM), 0-shot, descriptions=ON, sample_rows=ON, max_attempts=3, temp=0.0 | Core result — establishes accuracy before RAG |

~130 local inference calls total (no API limits). Results saved to `evaluation/results/baseline.csv`.

The baseline result feeds directly into Phase 5-B as the "before RAG" number. The primary thesis comparison is **baseline (static prompt) vs RAG pipeline**.

**Deferred (resume when needed):**
- Model ablations: additional local SQL-specialist models (≤10B, served via vLLM), if time permits
- Schema ablations: without descriptions, without sample rows
- Few-shot ablations: 0-shot vs 3-shot
- Self-correction ablation: 1 attempt vs 3 attempts
- Temperature ablation: 0.0 vs 0.3
- Difficulty breakdown: simple / moderate / challenging

These are fully designed and ready to run — just not prioritised yet. Resume by passing flags to `benchmark.py`.

### Files to Create
- `evaluation/test_questions.json`
- `evaluation/benchmark.py`
- `evaluation/metrics.py`
- `notebooks/03_evaluation_analysis.ipynb`

### Libraries
- `matplotlib`, `seaborn` (thesis-quality figures)
- `tqdm` (progress bars)
- `jupyter`

### Verification
```bash
python evaluation/benchmark.py --model xiyansql --output evaluation/results/
# Generates CSV with per-question results and summary metrics
```

---

## Phase 5-B: RAG Enhancement (Branch: `rag-enhancement`)

> **Authoritative detailed plan: [`RAG_plan.md`](RAG_plan.md)** — complete Phase 5-B execution spec
> (disjoint-pool methodology + leakage control, stratified dataset spec, subclass component design,
> incremental eval order, risks, verification). Phase 5 is **done** (baseline EX 90.2% on `main`);
> branch `rag-enhancement` is created and active. The sections below are the original design notes,
> now superseded in detail by `RAG_plan.md`.

**When:** After Phase 5 is complete on `main`. Create a new branch:
```bash
git checkout -b rag-enhancement
```

**Goal:** Replace static schema injection with a full RAG pipeline — dynamic schema retrieval and dynamic few-shot retrieval using FAISS vector search. Compare accuracy against Phase 5 baseline. This is a distinct thesis contribution: *"Does RAG improve Text-to-SQL accuracy on a domain-specific GST schema?"*

**Architecture change:**
```
Phase 1-5 (main):   Question → [full static schema + hardcoded few-shots] → LLM → SQL
Phase 5-B (branch): Question → FAISS search → [top-K tables + similar Q-SQL pairs] → LLM → SQL
```

---

### 5B-1. Schema Indexer (`core/schema_indexer.py`)

Reads the DB schema once and builds a FAISS index of table embeddings.

**M-Schema format** (more LLM-friendly than raw DDL):
```
Table: invoice_items
  invoice_id (INTEGER) -- FK to invoices.invoice_id
  igst_amount (REAL) -- Integrated GST, non-zero only for inter-state supplies
  cgst_amount (REAL) -- Central GST, non-zero only for intra-state supplies
  taxable_value (REAL) -- Value before tax; tax is computed on this
  ...
```

**Process:**
1. Read each table from DB via `sqlalchemy.inspect`
2. Merge with `descriptions.json` to add semantic column comments
3. Format each table as M-Schema text block
4. Embed each table block using `sentence-transformers` (`BAAI/bge-large-en-v1.5`)
5. Build FAISS index (one vector per table)
6. Save index + table metadata to `index/schema.faiss` + `index/tables.pkl`

```python
class SchemaIndexer:
    def build_index(self) -> None          # reads DB + descriptions → FAISS
    def load_index(self) -> FAISSIndex     # loads from disk
    def retrieve_tables(self, question: str, k: int = 5) -> list[str]  # top-K M-Schema blocks
```

---

### 5B-2. Q-SQL Store (`evaluation/rag_qsql_store.json`)

The few-shot retrieval pool. Built from Phase 5's gold Q-SQL pairs plus extra GST-specific examples.

**Structure:**
```json
[
  {
    "question": "What is the total IGST collected from inter-state B2B invoices?",
    "sql": "SELECT SUM(ii.igst_amount) FROM invoices i JOIN invoice_items ii ON i.invoice_id = ii.invoice_id JOIN suppliers s ON i.supplier_id = s.supplier_id WHERE i.invoice_type = 'B2B' AND i.place_of_supply != s.state_code;"
  },
  ...
]
```

Target size: 50–100 pairs covering all query categories (aggregation, filtering, ranking, time-series, domain-specific).

---

### 5B-3. RAG Retriever (`core/rag_retriever.py`)

At query time, embeds the user question and searches both FAISS indexes.

```python
class RAGRetriever:
    def __init__(self, schema_index_path, qsql_store_path, embed_model)
    def retrieve_tables(self, question: str, k: int = 5) -> list[str]    # top-K M-Schema blocks
    def retrieve_fewshots(self, question: str, k: int = 3) -> list[dict] # top-K Q-SQL pairs
    def retrieve(self, question: str) -> dict                             # both combined
```

**Embedding model:** `BAAI/bge-large-en-v1.5` (same model for both schema and few-shot retrieval — single model load).

---

### 5B-4. Updated Prompt Builder (`core/prompt_builder.py`)

Add a `RAGPromptBuilder` subclass that takes RAG-retrieved context instead of full static schema:

```python
class RAGPromptBuilder(PromptBuilder):
    def build_messages_from_rag(self, question: str, retriever: RAGRetriever) -> list[dict]
```

The system prompt structure changes:
```
SYSTEM: [rules + GST domain knowledge]

RETRIEVED SCHEMA (relevant tables only):
{top-K M-Schema table blocks}

RETRIEVED EXAMPLES (similar questions):
Q1: ... SQL1: ...
Q2: ... SQL2: ...

USER: {question}
```

---

### 5B-5. Updated Pipeline (`core/pipeline.py`)

Add a `RAGPipeline` subclass that wires in the `RAGRetriever`:

```python
class RAGTextToSQLPipeline(TextToSQLPipeline):
    def __init__(self, settings: Settings, retriever: RAGRetriever)
    def ask(self, question: str) -> PipelineResult
```

The original `TextToSQLPipeline` on `main` is untouched — `RAGPipeline` is a drop-in extension.

---

### 5B-6. XiYanSQL-QwenCoder-7B — ✅ now serving (pulled forward to primary)

The specialized Text-to-SQL model recommended by the guide, `XGenerationLab/XiYanSQL-QwenCoder-7B-2504`, is **already serving** via local vLLM on the lab HPC (no longer gated on Phase 5-B/6). Full serving recipe lives in `CLAUDE.md` → "HPC / vLLM serving". Used now as the primary inference path, not just an RAG experiment.

- **Dialects**: SQLite, PostgreSQL, MySQL — all supported (matches our `gst_official` PG DB)
- **Inference**: vLLM, OpenAI-compatible endpoint on port 8765, `--enforce-eager`, `--max-model-len 32768`
- **Client**: `VLLMClient` in `core/llm_client.py` + `make_client(provider="vllm", ...)` — OpenAI-compatible wrapper with `base_url` (done in Phase 2)

---

### 5B-7. RAG Evaluation

**Active (run now):** Single RAG run, same 100 questions as Phase 5 baseline.

| Run | Config | Purpose |
|-----|--------|---------|
| RAG pipeline | Schema RAG + Few-shot RAG, XiYanSQL-7B (local vLLM), max_attempts=3, temp=0.0 | Core RAG result |

~130 local inference calls. Results saved to `evaluation/results/rag.csv`.

**Primary thesis comparison:** `baseline.csv` vs `rag.csv` — does RAG improve accuracy on GST domain?

**Deferred RAG ablations — PARKED (2026-06-29).** Schema-only / few-shot-only / both and the
few-shot top-K (Grid-B k3/k5) are **done** (2×2 in `results/README.md`). The remaining ablations are
deliberately **parked**, not abandoned: assessed as **unlikely to move EX past the locked 98.2%**, so
they would enter the thesis only as "we also checked X, confirms the design choice" footnotes — not as
result-movers. Resume only if the residuals {62,107} become a priority or a reviewer asks. Rationale
per item below; full list in `RAG_plan.md` §9 "Deferred items".
- Category-aware rerank, predicted-vs-oracle (#7) — few-shot already retrieves good same-pattern demos;
  won't fix flaky #62 or the 3-table #107. Code exists (`rag_category_weight=0`, off).
- Pool-size sweep (20/50/100/142, #13) — a *reduction*/saturation study; by design can't *raise* EX
  (best case = unchanged). Robustness story, not accuracy.
- Top-K table sweep (k=3 vs 5) + hybrid table-retrieval — improve table coverage (decode-cover 20%),
  but decode is already **100% EX** via few-shots → no headroom to convert into EX.
- Cross-encoder reranker (#4) / dynamic-k (#5) — overkill on the 142-pair hand-curated pool; dynamic-k
  also hurts retrieval reproducibility.
- RAG + a 2nd local SQL model — comparison breadth, not this model's EX; gated on serving a 2nd model.

---

### Files to Create (Phase 5-B branch)

- `core/schema_indexer.py` — M-Schema builder + FAISS index
- `core/rag_retriever.py` — dual FAISS retrieval (schema + few-shots)
- `evaluation/rag_qsql_store.json` — 50–100 GST Q-SQL pairs
- `index/` — FAISS index files (gitignored, regenerated on first run)
- Updates to `core/prompt_builder.py` — `RAGPromptBuilder`
- Updates to `core/pipeline.py` — `RAGTextToSQLPipeline`
- Updates to `core/llm_client.py` — `VLLMClient`

### Libraries (Phase 5-B additions)

```
sentence-transformers>=2.7
faiss-cpu>=1.8          # or faiss-gpu when GPU available
# vllm>=0.5            # when GPU available
```

### Hardware Requirements

| Component | Minimum | For XiYanSQL-7B |
|-----------|---------|-----------------|
| GPU VRAM | None (CPU inference possible, slow) | 10 GB (fp16) / 16 GB (bfloat16) |
| RAM | 16 GB | 32 GB |
| GPU | None | RTX 3080 / RTX 4090 / A100 |

### Verification
```bash
git checkout rag-enhancement
python core/schema_indexer.py          # builds FAISS index
python -c "
from core.rag_retriever import RAGRetriever
r = RAGRetriever('index/', 'evaluation/rag_qsql_store.json', 'BAAI/bge-large-en-v1.5')
tables, shots = r.retrieve('Which state has highest IGST collection?')
print('Tables:', [t[:50] for t in tables])
print('Shots:', [s['question'] for s in shots])
"
```

---

## Phase 6: Production Hardening (Govt Deployment)

**When:** After thesis demo is validated and green light is received.

### 6-DEPLOY: IITH Portainer/H100 box — IN PROGRESS (2026-07-07)

Advisor (Subbareddy Batreddy) asked to deploy on a lab GPU server — **replaces** the
borrowed shared-SLURM HPC as the deployment target. Access is **Portainer web UI only**
(`https://103.230.85.116/portainer`, no SSH); work inside one shared container
`iit-hyderabad` (Ubuntu 22.04, 128 CPU / 760 GB RAM / **1× H100 NVL 95.8 GB**, driver
575 / CUDA 12.9). Our dir: `/workspace/IITH_GST/Subbareddy/ankit-text2sql`.

**Setup model:** collapse the current *laptop + HPC* split into ONE container — two
conda envs: `env-app` (`pip install -r requirements.txt`, CPU torch, pipeline/Streamlit/
seed) + `env-serve` (`pip install vllm`, GPU torch) talking over `localhost:8765` (no
tunnel). No code/requirements change — identical envs, just co-located.

**Done this session (2026-07-07):**
- Merged `rag-enhancement` → `main` (fast-forward, 0 conflicts; base pipeline files
  byte-identical, RAG is additive/opt-in) and pushed. `main` = `origin/main`.
- Versioned `evaluation/results/` as a proof-of-work snapshot (baseline EX 90.2%, Full
  RAG 98.2%) tied to the code commit — CSVs + README 2×2 + per-question jsonl traces
  (~11 MB). Non-reproducible once the 4th schema lands, so frozen now.
- Wrote `deploy_runbook.md` (local, gitignored) — paste-by-block steps §0–§9.

**⚠️ BLOCKER — GPU oversubscribed:** H100 at ~91/96 GB used (mayank's Qwen3.6-27B-FP8
@ util 0.80 ≈ 76 GB + giridhar's rag-chatbot ≈ 15 GB). A 7B needs ~16–20 GB → cannot
serve until the card frees. Awaiting a coordinated VRAM window (told "come after lunch").
Ports taken: 8001/8011/8080/~3000; **8765 free** (confirm before serving). Serve with
**LOW** `--gpu-memory-utilization` (~0.25), never grab 0.80 on the shared card.

**Non-GPU steps doable now (runbook §1–§6):** verify space (~25–30 GB, models not repo
— clone is ~5 MB) → secure fine-grained-PAT clone (read-only, entered at prompt, no
credential helper) → own Miniconda `env-app` → user-local Postgres cluster on 5433 →
`.env` from template → seed + verify counts (20/63/12). GPU-gated (§7–§8): serve vLLM
(FlashInfer/nvcc traps guarded), run app / RAG benchmark.

**Safety:** shared container, others' work LIVE — never stop/kill it; work only in our
dir; co-tenants have root → keep the clone PAT off disk, strip after; don't use mayank's
`(base)` conda.

### 6A. Database Hardening
- PostgreSQL already in use (`gst_official`) — migration done in Phase 1 redo
- Create a dedicated read-only role for the pipeline (currently uses `default_transaction_read_only`)
- Connection pooling via SQLAlchemy pool_size or PgBouncer

### 6B. API Backend
- FastAPI wrapper around `core/pipeline.py`
- `POST /query` → `{question, model}` → `{sql, data, row_count, execution_time}`
- Govt website calls this via REST/AJAX

### 6C. Local GPU — ✅ already serving (HPC)
- vLLM serving of `XiYanSQL-QwenCoder-7B-2504` is already working on the lab HPC (recipe in `CLAUDE.md`)
- Remaining for production: a permanent/owned GPU box (vs. the shared SLURM node), and config `default_provider = "vllm"`, `default_model = "xiyansql"`

### 6D. Security
- Audit logging: log every query (question, SQL, result count, user ID)
- Per-IP rate limiting via `slowapi`
- Prompt injection defense (sanitize user input)
- HTTPS at reverse proxy (nginx)

### 6E. Caching
- Hash-based query cache (exact match on normalized question)
- Reduces redundant LLM inference for repeated questions

### 6F. Hindi/Regional Language Support (Future)
- Modify system prompt to accept Hindi/Hinglish questions
- Or add translation preprocessing step
- Qwen models have multilingual capability

---

## Phase 7: Second-Model Comparison — Qwen3.6-27B-FP8 (Branch: `model-qwen27b`)

**When:** Now (Phase 6 deploy parked on GPU VRAM blocker). A second model became available via a
lab-hosted API; test it on the **frozen 112-question eval set** for a head-to-head vs XiYanSQL-7B
before touching schemas.

**Model:** `Qwen/Qwen3.6-27B-FP8` — hosted at `https://api.jaypokale.me/v1` (Cloudflare-fronted,
OpenAI-compatible). This is the **same H100 box** as the Phase 6 deploy target (co-tenant's model),
now exposed as an endpoint. API key lives in `.env` (never committed); doc `api_documentation.md` is
gitignored/untracked.

**Role — upper-bound comparison baseline ONLY, not a deployment candidate.** At 27B it exceeds the
**≤10B deployment cap**, so it fills the "one larger model as upper-bound" slot the plan reserves
(§Context) — it measures how much headroom a bigger model buys over the deployable 7B, nothing ships
on it.

### 7.1 Why it needs code (not pure opt-in)
Hosted-API plumbing was **deliberately removed** when Groq/OpenRouter were dropped. Re-adding it
touches base files, hence the branch:
- `core/llm_client.py` — `VLLMClient`/`make_client` hardcode a vLLM endpoint and ignore api_key/headers.
- `config/settings.py` — `validate_provider` **hard-rejects** any provider ≠ `"vllm"`.

### 7.2 Client generalization
- Add `default_headers` support (Cloudflare WAF **blocks default SDK user-agents** → must send a
  browser `User-Agent` or the connection is refused).
- Honor a real `api_key` + `base_url` from settings/`.env`.
- Relax `validate_provider` + `make_client` to allow an OpenAI-compatible hosted provider alongside
  `vllm` (keep the vLLM path byte-intact). Local-only remains the *default*; this is an opt-in second provider.

### 7.3 Reasoning-model handling — **probed 2026-07-08**
Qwen3.6 is a **reasoning model** (heavy thinking per call). Probe findings (`scratchpad/probe_qwen*.py`):
- **Reasoning is server-side separated → `content` is already clean SQL.** It lands in a nonstandard
  `message.reasoning` field (via `msg.model_extra["reasoning"]`), **not** `content` and **not** the
  standard `reasoning_content`. No inline `<think>` in content. ⇒ **`_extract_sql` needs NO change.**
- **`max_tokens` must be raised (~4000).** Reasoning appetite is high + variable: simple Q = 265
  completion tokens, a 3-table ranking Q = 1646. The current 1024 default **would truncate** harder
  questions. Both probes returned `finish_reason=stop` at 2048/3000 — no truncation with headroom.
- **Context window = 32768** (confirmed via `/models max_model_len` + forced over-length 400 error) —
  **same as our XiYanSQL vLLM** (apples-to-apples).
- **Real static prompt = 28.8K Qwen tokens** (endpoint-measured, *higher* than the 26.5K o200k proxy /
  ~20.1K chars/4 proxy in the results README) → only ~4K completion room in the 32K window. Set
  **`qwen_max_tokens=3000`** (attempt-1 fits at 31.8K, ~1K buffer). Self-correction resends the full
  28.8K prompt + appends error turns → a grown turn can exceed 32K → **`VLLMClient` catches the
  over-length `BadRequestError` and returns ""** (graceful fail, no run crash).
- **Tight-fit is a finding, not just a config detail:** it hits only the **two full-static configs**
  (baseline + few-shot-only); the retrieved-schema RAG configs (~12.6K real Qwen tokens) have ample
  room. A 27B *reasoning* model is context-constrained by the static-prompt design → extra motivation
  for RAG (smaller prompt = full reasoning budget).
- **Cloudflare WAF confirmed:** browser `User-Agent` header is mandatory; connection works with it.
- Doc suggests `temperature=0.2`; eval keeps `0.0` for determinism — probe emitted valid SQL at 0.0.

### 7.3b Thinking-OFF switch — **found 2026-07-08 (game-changer)**
Reasoning ≈30s/call made a full 112×3 eval impractical from the laptop. Tested 5 ways to disable it:
- `logit_bias {151649:-100}` (friend's hack) — **zero effect** (byte-identical to control; server ignores/wrong token).
- prompt "no thinking" (friend's hack) — marginal (27s, still 4861 chars reasoning).
- `/no_think` tag (Qwen3 canonical) — partial (21–23s, still ~3600–4000 chars reasoning).
- **`extra_body={"chat_template_kwargs":{"enable_thinking":False}}` — FULL KILL: 30.9s→1.3s (~24×),
  completion 1617→65 tok, reasoning 0 chars, SQL still correct.** ✅ This is the server-honored switch.

**Consequences:** (1) thinking-off eval is cheap → runs from laptop in minutes; (2) 65-tok output ⇒
**no 32K-window tightness** (the `qwen_max_tokens=3000` + guard only matter for thinking-ON); (3)
run-on-box (§Phase 7 "run inside box") is no longer *required* for speed — only optional for unattended
thinking-ON runs. **Report two Qwen configs:** thinking-OFF (fast, deploy-style) vs thinking-ON (quality
ceiling). Wire `enable_thinking` as a qwen-only settings toggle passed via `extra_body` in `VLLMClient`.

### 7.4 Evaluation
Same frozen 112 gold set, benchmark is provider-agnostic (only the client swaps).
- **Primary comparison = static baseline** (identical static prompt) vs XiYanSQL baseline **90.2%** →
  `evaluation/results/qwen27b_baseline.csv`.
- **Optional** RAG (`--rag-mode both`) vs XiYanSQL Full RAG **98.2%** → `qwen27b_rag.csv`.
- **Cost caveat:** 26.5K static prompt + ~1000 reasoning tokens × 112Q × runs × ≤3 attempts is heavy,
  and the hosted endpoint has unknown rate/context caps. **Screen with `--runs 1`**, confirm context
  window ≥28K, then `--runs 3` if stable.

### 7.5 Results — COMPLETE (2026-07-10, all thinking-OFF, runs=3, all ±0.0)

| Configuration | XiYanSQL-7B EX | Qwen-27B EX | Δ |
|---|---|---|---|
| Baseline (static) | 90.2% | 92.9% | +2.7 |
| Schema-only | 86.6% | **94.6%** | +8.0 |
| Few-shot only | 97.3% | 100% | +2.7 |
| Full RAG | 98.2% | **100%** | +1.8 |

Files: `qwen27b_{baseline,rag_schema,rag_fewshot,rag}.csv` + per-config traces. Key findings:
1. **Schema-retrieval interference is model-dependent** — schema-only *hurt* the 7B (−3.6) but
   *helps* the 27B (+1.7; fail-set strict subset of its baseline, zero new breaks). The pruned
   ~57%-cheaper prompt is safe for the large model, risky for the deployable one.
2. **RAG still pays at 27B**: +7.1 over its own baseline (92.9→100) — scale doesn't make
   retrieval redundant on this schema. Decode solved natively by reasoning (100% at static);
   **ranking** is the generalist's weak category (50% static → 100% with few-shots).
3. **100% ceilings** (both few-shot configs) sharpen the W1 distinguishability audit (Phase 9
   Tier-1) — toy-DB perfect scores need the adversarial-variant check to be credible.

### 7.6 UI model toggle (plan change, 2026-07-11)

Original framing ("upper-bound baseline only, nothing ships on it") is softened: both models are
live comparison candidates, and the Qwen endpoint costs us zero VRAM (co-tenant already serves it
on the H100 box). So the UI must not hardcode a provider:
- `ui/app.py` currently hardcodes `provider="vllm", model="xiyansql"` (line ~82) → replace with a
  **sidebar provider/model selector** (XiYanSQL-7B local vLLM ↔ Qwen3.6-27B hosted), default XiYan.
- Pipeline is re-inited on switch (`load_pipeline(provider, model)` already parameterized — only
  the hardcoded call site changes).
- The **≤10B deployment cap still stands** for the final govt deployment story; the toggle is for
  flexible comparison/demo, not a deploy decision.

**Merge:** fold to `main` once the comparison table lands (additive second provider, vLLM default
untouched) — same clean-merge discipline as `rag-enhancement`. Table has landed (above). UI toggle
(§7.6) **deferred to demo-time** — UI not relied on now, does not gate the merge. Thinking-ON run
skipped (thinking-OFF already at 100%; nothing to add).

---

## Phase 8: New Schemas (Branch: `new-schema`) — extends Phase 1

**When:** After the Phase 7 model comparison. New government schemas were provided (beyond the current
EWB / GSTR-3B / GSTR-7 + pending 4th). Done on a dedicated branch; `main` stays clean.

**Received schema set (2026-07-13, `database/New_schemas/` → promoted to `Official_Schemas/`):**
- `ewb.sql`, `gstr7.sql` — comment reformatting only, zero structural change vs v1.
- `gstr3b.sql` — **normalized 17-table GSTR-3B** (`public.tbl_gst_rtn_r3b*`): main + 4 link parents
  (`inward_sup`, `itc_elg`, `sup_details`, `tx_pmt`) + 12 detail tables; sections stored as rows
  (ITC by `ty`, payments per liability line `liab_ldg_id`/`trans_typ`). `gstin`/`ret_period` only on
  the main table — details reach it via 2–3 join hops.
- `gstreg.sql` — **NEW module** (`common`): `t_all_delers_api_v_t` dealer master (1 row/GSTIN,
  UNIQUE(gstin)) + `mst_state_jurisdiction_code` (stjd → division/range/unit, UNIQUE(state_jur_code)).
  Supplies the taxpayer identity/status/geo decode for all fact modules.
- `common_masters.sql` — first standalone DDL for `mst_fy_years_t` + `mst_3bd_months_t`.

**KEY DECISION (2026-07-13, guide):** keep the **latest** GSTR-3B schema = normalized `gstr3b.sql`;
**drop the flat MV `gstr3b_new.sql`** (`live_reports.r3b_comphrehensive_..._partitioned`) entirely.
Impact audit before removal:
- *Data lost:* 6.1(A)/(B) RCM payment split (0 golds / 0 pool pairs ever used it), `fy_flag` on the
  fact (FY scoping reshapes to `ret_period → mst_3bd_months_t.ret_period_fl → fy_flag →
  mst_fy_years_t.flag_fy` — every FY question gains a join), `mnth_id` (0 uses),
  `return_from/to_date` + tax-payable rollup (derivable), `fil_dt` native DATE (normalized is
  VARCHAR DD-MM-YYYY → `TO_DATE`).
- *Breakage (rebuilt from scratch anyway per Phase 8):* 38/112 golds + 54/142 pool pairs target the
  MV; `config/prompts.py` module map + 2/5 few-shots; `seed_data_official.py` MV block;
  `descriptions_official.json` MV key (145 cols) → 17 keys; `core/schema_indexer.py::_CORE_TABLES`
  MV entry → `public.tbl_gst_rtn_r3b`.
- *Watch-outs for v2:* difficulty profile shifts (every 3B question gains 1–3 joins — baseline EX not
  comparable to v1's 90.2); the 5 supply detail tables have IDENTICAL columns
  (`txval/iamt/camt/samt/csamt`) → adversarial seed must give each section distinct value magnitudes
  or the distinguishability audit's table-swap mutator collides half the module; static prompt
  shrinks (normalized DDL 17KB vs MV 33KB) easing the Qwen 32K window.

**RULE: received schema DDLs are READ-ONLY** — external artifacts from the government team; never
edit their content (not even comments/join hints). Stale references inside them are corrected in
project-owned layers (`descriptions_official.json`, `config/prompts.py`), not in the files.
Known stale bits carried as-received: `gstreg.sql` join hint still names the dropped MV;
`common_masters.sql` comments still describe MV-era `<fact>.fy_flag`/`mnth_id` join keys (no
current fact table carries either — FY path is `ret_period → mst_3bd_months_t`); `gstr7.sql` has a
stray trailing `-`.

**Scope:**
- [DONE 2026-07-13] Swap `database/Official_Schemas/` to the new 5-file set **as received** (ewb,
  gstr7, normalized gstr3b, gstreg, common_masters); MV `gstr3b_new.sql` removed.
- Extend `database/descriptions_official.json` (schema-qualified keys, LLM-HIDE annotations).
- Rewrite seed (`database/seed_data_official.py`): 17-table FK-consistent GSTR-3B + gstreg tables,
  **adversarial values from day one** (audit-looped, distinct magnitudes per section table).
- `SchemaExtractor` already multi-schema — confirm the new schema/tables are picked up + qualified.
- Update `core/schema_indexer.py::_CORE_TABLES` + `config/prompts.py` (module map, quoting rule
  line for dropped `live_reports`, 2 MV few-shots).
- Rebuild gold eval set + RAG pool from scratch for the new schema set (same disjoint-pool leakage
  discipline as `RAG_plan.md` §2); held-out set (W2) authored here.
- If the schema effort grows its own methodology/spec → split to `SCHEMA_plan.md` (the way Phase 5-B
  earned `RAG_plan.md`); until then it lives here.

**Pipeline is schema-agnostic** — only `database/` + descriptions + gold/pool data change; `core/` is
untouched.

---

## Phase 9: Validity Hardening (review-driven, examiner-proofing)

**When:** Toward thesis write-up. Driven by the external review (`thesis_review.md`, 2026-07-02,
reviewed at `rag-enhancement`/`8128db4`). The engineering is strong; the exposure is **evaluation
validity**, not code. These items decide whether the headline (Full RAG 98.2% vs baseline 90.2%)
survives an examiner. **Backing spec = `thesis_review.md` §3–§8** (this section is the actionable
checklist; the rationale lives there, same relation as Phase 5-B ↔ `RAG_plan.md`).

**Where items fold:** several overlap existing branches — the ≤10B peer folds into the model branch
(Phase 7-adjacent); the held-out set folds into Phase 8 (a fresh module authored-once, configs frozen,
run-once ≈ a held-out confirmation set). Cross-refs noted per item.

### Tier 1 — validity (do all; these gate the headline's credibility)

1. **Distinguishability audit + adversarial seed data (W1 — most serious).** ✅ **Audit DONE
   (2026-07-11):** `evaluation/distinguishability_audit.py` (3 mutators: column-swap same-type,
   filter-drop, table-swap shape-compatible; deterministic seed=42) → 268 variants, 261 ran,
   **23 matched gold → 19/111 questions (17.1%) collide**; GSTR-7 worst (29.0%), challenging 33.3%.
   Manual classification: 6 variants are **domain-invariant equivalences** (CGST=SGST equal-split law,
   igstval=0 intra-state — would collide on real data too), 17 are **genuine toy-seed coincidences**
   → net 15/111 (13.5%) seed-fixable looseness. Full findings + per-collision fix list in
   `results/README.md`; report `results/distinguishability_audit.csv`. **Adversarial re-seed deferred
   to Phase 8** (roadmap: seed is rebuilt there anyway, audit-looped from day one; audit script is the
   loop's checker). Every reported EX carries the ~13.5% upper-bound caveat until the v2 re-run.
2. **Held-out confirmation set (W2).** k/mode/pool-fix/gold-revisions all touched the same 112 →
   adaptive bias. 30–40 **fresh** questions, authored once, frozen configs, run once, reported
   unconditionally. **Fold into Phase 8** (new-module questions, run-once). Bounds the bias instead of
   arguing it.
3. **Statistical treatment (W4).** ✅ **DONE (2026-07-11):** `evaluation/stats.py` — exact-binomial
   McNemar (discordant counts are single-digit; chi-square invalid) + Wilson 95% CIs, majority-binarized
   per question, 10 unit tests. Results: **RAG gains significant for both models** (XiYan
   baseline→full-RAG b=1/c=10 p=0.0117; Qwen b=0/c=8 p=0.0078); **schema-retrieval interference NOT
   significant either direction** (XiYan −3.6 p=0.34; Qwen +1.7 p=0.5), nor cross-model gaps (p≥0.5) —
   these must be worded as mechanisms, not effects. Flip lists corrected the residuals narrative:
   **#96/#107 passed baseline; few-shot RAG regressed both; full RAG recovered only #96** → #107 is a
   RAG-introduced regression, #62 is baseline-flaky (1/3). Tables → `results/stats_wilson_ci.csv`,
   `results/stats_mcnemar.csv`; readings in `results/README.md`.
4. **Run the two missing ablations (W3).** descriptions on/off, and self-correction attempts 1-vs-3
   (+ attempts-distribution table). Evidences 2 of 3 claimed contributions — else cut the claims. One
   benchmark flag each.
5. **Commit tests + fix two real bugs (Critical 1/2/5).** `tests/` is empty despite the "unit-tested"
   claim → reconstruct metrics+validator tests. Bugs: (a) EX `permutations()` blowup can **hang** the
   benchmark on a `SELECT *` (cap `npred`, or multiset-match values first); (b) comma-FROM allow-list
   bypass in `sql_validator._extract_table_names` (thesis must not call the allow-list complete).

### Tier 2 — strengthens the claims (if time)

6. **Second ≤10B SQL model** through the identical harness → class-of-model evidence (Qwen-27B is an
   *upper-bound* only; a peer ≤10B is the real multi-model result). **Fold into the model branch** while
   plumbing is warm. Counters W5 / Viva-Q5.
7. **Guide spot-checks ~20 golds** — inter-annotator signal (W5, Viva-Q10); someone else's half-day.
8. **Real tokenizer counts** — replace chars/4 in the efficiency table (Qwen already measured 28.8K
   real; use the actual tokenizer for XiYan). Makes the "~57% fewer tokens" headline solid.
9. **Paraphrase-robustness probe** (10–15 paraphrases; phrasing sensitivity already known).
10. **NL answer-generation stage** — closes the stated "non-technical GST officer" goal; low effort,
    high demo value.

### Tier 3 — post-thesis / publication (parked)
Benchmark release (needs schema clearance — strongest pub card), schema-retrieval-interference study,
self-consistency decoding, value/cell retrieval, abstention/confidence, Phase 6 hardening. See
`thesis_review.md` §5.10.

**Explicitly NOT before submission** (review §8 agrees): cross-encoder reranker, dynamic-k, AST index,
pool-size sweep (can't move residuals {62,107}); agentic/decomposition frameworks (contradict the
token-efficiency story).

---

## Timeline

| Week | Phase | Milestone | Branch |
|------|-------|-----------|--------|
| 1 | Phase 1 (original) `[DONE]` | SQLite toy schema + seed data — superseded | `main` |
| 2 | Phase 2 `[DONE]` | LLM generates SQL from natural language | `main` |
| 3 | Phase 3 `[DONE]` | Full pipeline: question → validated SQL → results | `main` |
| 4 | Phase 4 `[DONE]` | Streamlit demo built | `main` |
| 5 | Phase 1 (redo) `[DONE]` | Official schemas (EWB, GSTR-3B, GSTR-7) seeded + descriptions + multi-schema extractor | `main` |
| 6 | Infra `[DONE]` | Local vLLM serving XiYanSQL-7B-2504 on HPC, endpoint smoke-tested | `main` |
| 7 | Phase 2 `[DONE]` | vLLM client wired into pipeline; hosted APIs (Groq/OpenRouter) dropped — local-only inference | `main` |
| 7 | Phase 2/3 verify `[DONE]` | End-to-end run on `gst_official` via tunneled vLLM PASSED (2026-06-15); EWB queries correct; found GSTR-7↔GSTR-3B module confusion | `main` |
| 7 | Phase 2 prompt-hardening `[DONE]` | Diagnostic-driven general prompt+description fixes (routing, aggregation grain, amount-column semantics); EX 11/16→15/16 on 16-Q probe; residual name-collision documents RAG/few-shot motivation | `main` |
| 7 | Phase 5 `[DONE]` | 112-pair gold set + full baseline (runs=3) on XiYanSQL-7B → EX 90.2% ±0.0; failures triaged, general (non-overfit) fixes applied, residuals scoped as RAG targets | `main` |
| Next | Phase 1 (redo) | 4th schema from guide | `main` |
| **Now** | Phase 5-B `[DONE]` | RAG branch complete: FAISS schema+few-shot retrieval, RAG pipeline, full Grid-A (2×2). **Full RAG EX 98.2% (vs 90.2% baseline) at ~57% fewer tokens; decode 25%→100%.** Schema-alone hurts; few-shot is the workhorse; schema pays off only with few-shots | `rag-enhancement` |
| Parked | Phase 6-DEPLOY `[PARKED]` | Deploy to IITH Portainer/H100 box. RAG merged→`main` + results versioned (proof snapshot) + `deploy_runbook.md`. **Stalled** — GPU VRAM blocker + redirected to Phase 7/8; resume when GPU frees | `main` |
| **Now** | Phase 7 `[IN PROGRESS]` | 2nd-model comparison: Qwen3.6-27B-FP8 (lab-hosted API) on frozen 112 set vs XiYanSQL-7B. Upper-bound baseline only (27B > 10B deploy cap); reasoning model → client generalization (headers/api_key) + reasoning-output extraction | `model-qwen27b` |
| **Next** | Phase 8 `[PLANNED]` | New government schemas — pasted into branch; extend DDL/descriptions/seed + grow gold/RAG pool; `main` kept clean | `new-schema` |
| **Next** | Phase 9 `[PLANNED]` | Validity hardening (review-driven, `thesis_review.md`): distinguishability audit + adversarial data, held-out set, McNemar/CIs, missing ablations, tests+bug-fixes, ≤10B peer. Examiner-proofs the headline | folds into model/schema branches + `main` |
| TBD | Ablations | All deferred ablation studies | `main` / `rag-enhancement` |
| TBD | Phase 6 | FastAPI + security hardening (when green light) | `main` (merge) |

---

## Dependencies (`requirements.txt`)

```
# Core
openai>=1.0          # HTTP client for the local vLLM OpenAI-compatible endpoint
sqlalchemy>=2.0
sqlparse>=0.5
python-dotenv>=1.0
pydantic>=2.0
pandas>=2.0

# Seed Data
Faker>=28.0

# UI
streamlit>=1.35

# Evaluation
matplotlib>=3.8
seaborn>=0.13
tqdm>=4.66
pytest>=8.0

# Notebooks
jupyter>=1.0

# Database (Phase 1 redo — now required)
psycopg2-binary>=2.9

# Production (Phase 6 — uncomment when needed)
# fastapi>=0.111
# uvicorn>=0.30
# slowapi>=0.1
# vllm>=0.5
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| ≤10B models underperform on complex JOINs | Self-correction handles many failures. Document as thesis finding |
| HPC GPU unavailable during a work session | Inference is local-only; no API fallback. Mitigation: `tmux` + re-allocate when a GPU frees up; serving recipe is fully documented so re-spin is fast |
| Official schemas too large for prompt | 19+ tables with dense column comments. RAG (Phase 5-B) is the natural fix — retrieve only relevant tables per query. Static prompt approach requires careful column pruning (use LLM-HIDE annotations). |
| Schema complexity: padded strings, quoted columns, VARCHAR dates | Document in descriptions_official.json as explicit LLM instructions (TRIM, TO_DATE, double-quote). Test with representative queries. |
| 4th schema not yet received | Build pipeline to be modular — add new schema/descriptions without touching core pipeline |
| Shared HPC GPU contention / time limits | Lab SLURM node is shared; jobs have `--time` caps and CPUs/GPUs get fully allocated. Mitigation: `tmux` + re-allocate when free, never cancel others' jobs (no API fallback — local-only) |
| SQL injection in govt deployment | Validator blocks non-SELECT + DB has read-only role. Defense in depth |
| FAISS retrieval fetches wrong tables | 19+ tables makes this more likely than before. Mitigation: always include core tables (tbl_ewb_parta_ewb, r3b_*, tbl_gst_rtn_r7) regardless of retrieval |
| RAG branch diverges too far from main | Keep `RAGPipeline` as a subclass — base pipeline on main is untouched. Merge is clean. |
| XiYanSQL not available via API | Confirmed — no public API. Use only with local GPU. Phase 5-B experiments without it if GPU unavailable. |

---

## Future Work / Known Limitations

### Prompt Maintenance Gap
`config/prompts.py` contains hardcoded sections — TABLE RESPONSIBILITIES, COLUMN OWNERSHIP, FOREIGN KEY RELATIONSHIPS, COMMON JOIN PATTERNS — that describe the schema but are not auto-generated from the database. With the pivot to official schemas (19+ tables), this gap is now larger: the hardcoded sections must be rewritten for EWB, GSTR-3B, and GSTR-7.

**Plan:** Rewrite the prompt sections for the official schemas when `descriptions_official.json` is ready. The LLM-HIDE annotations in the official schema files tell us which columns to exclude from the prompt.

**Clean fix (Phase 5-B or later):**
- Move TABLE RESPONSIBILITIES and COLUMN OWNERSHIP into `descriptions_official.json`
- Auto-generate FOREIGN KEY RELATIONSHIPS inside `SchemaExtractor` — SQLAlchemy `inspect().get_foreign_keys()` reads this directly
- COMMON JOIN PATTERNS stays hardcoded — it is domain knowledge (Part-A ↔ Part-B bridge via ewb_no, GSTR-7 FK naming quirk, etc.) not derivable from schema metadata alone

### Static-Prompt Ceiling: Lexical Name-Collisions (finding, 2026-06-15)
A diagnostic-driven prompt-hardening pass (16-Q probe, all 3 modules) lifted execution accuracy from 11/16 to 15/16. General, schema-grounded fixes — a "how to build the query" reasoning playbook, symmetric MAIN-table grain statements, and **point-of-selection** description fixes (warn the wrong column/table, make the correct one self-advertise) — reliably fixed **module mis-routing**, **aggregation-grain** (one row ≠ one entity ⇒ SUM+GROUP BY), and **amount-column semantics** (TDS = `iamt+camt+samt`, not `amt_ded`), and these generalised across phrasings.

The residual failure is a **near-exact name-collision**: "how many e-way bills *were cancelled*" routes to the `canceldet` event log (count 2) instead of `tbl_ewb_parta_ewb.status='CNL'` (count 4). It is **phrasing-sensitive** — "how many *cancelled e-way bills*" routes correctly — and resisted five layers of prose guidance. This is the empirical ceiling of static prompting and a concrete motivation for Phase 5-B: semantic schema retrieval (RAG) and few-shot demonstration are the mechanisms expected to stabilise table selection where surface-name matching misleads. The 16-Q probe (`/tmp/t2s_diag.py`) is a good seed for the Phase 5 gold set.

**Static-Prompt Ceiling, confirmed at 112-question scale (finding, 2026-06-17):** A full baseline (runs=3) on the 112-pair gold set scored **EX 90.2% ± 0.0, VER 97.6% ± 0.5** (up from 86.6% pre-triage). Triage isolated a second, stronger ceiling beyond the name-collision: the model **derives** GSTR-3B financial-year/quarter labels from the period column (e.g. `TO_CHAR(TO_DATE(ret_period,'MMYYYY'),'YYYY')`, or hallucinates a non-existent `fp` column) instead of JOINing the decode tables (`common.mst_fy_years_t`, `mst_3bd_months_t`) — yielding the wrong (calendar, not financial) year. A forceful, general *"labels need the decode JOIN — never derive"* prompt rule was tried and **reverted**: it gave zero EX gain (the `decode` category stayed at 25%) and introduced a routing regression, confirming the behaviour resists prose. This is the headline Phase 5-B motivator alongside the name-collision; few-shot demonstration / semantic retrieval are the expected fixes. Fixes that *did* generalise (kept): GSTR-3B tax payable = `iamt+camt+samt+csamt` (the `*_tx` columns / `tbl_gst_rtn_r7_tax_pay` belong to GSTR-7), plus test-quality gold corrections — ranking golds reduced to the minimal entity projection, a broken filings-vs-taxpayers count (#77: 24→4), and a boundary-tie top-N (#72: top-5→top-4).

### Schema Pivot (Phase 1 redo)
The original 7-table SQLite toy schema (`database/schema.sql`) is superseded by the official government schemas and has been removed from the working tree (recoverable via git history). The pipeline itself (Phases 2–4 code) is database-agnostic — only `database/connection.py`, `config/settings.py`, `config/prompts.py`, and `database/descriptions_official.json` need updating for the new schemas.

---

## Thesis Contribution Framing

1. **Domain-specific Text-to-SQL for Indian GST data** — novel application domain, no prior work
2. **Schema enrichment via column descriptions** — quantified through ablation study
3. **Self-correction for open-source models** — demonstrates iterative error feedback value
4. **Multi-model comparison under constraints** — practical comparison of sub-10B vs larger models on domain-specific data
5. **RAG-augmented pipeline** (Phase 5-B) — Schema RAG + Few-shot RAG using FAISS; quantifies accuracy gain over static prompting on a domain-specific schema
6. **Deployment architecture** — full pipeline from demo to government-deployable API
