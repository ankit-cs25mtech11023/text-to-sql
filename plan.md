# Text-to-SQL Pipeline for GST Data — Implementation Plan

## Context

Thesis project: build a Text-to-SQL pipeline that converts natural language questions about GST (Goods and Services Tax) transaction data into SQL, executes it, and shows results. The advisor's pipeline is: **NLP input → LLM (+ schema/datatypes/descriptions) → SQL command → Execute → Show results**.

**Key constraints:** open-source LLM ≤10B params (future GPU can only handle this size), Groq API (no local GPU yet), SQLite for demo, Streamlit frontend. Fraud detection on the whiteboard is a different student's thesis — not in our scope. One larger model (70B) included only as upper-bound baseline for thesis comparison — not a deployment candidate.

---

## Project Structure

```
Dev/
├── .env.example / .env              # GROQ_API_KEY, DB path
├── .gitignore
├── requirements.txt
├── config/
│   ├── settings.py                  # Central config (model, DB URL, limits)
│   └── prompts.py                   # All prompt templates
├── database/
│   ├── schema.sql                   # DDL for GST tables (SQLite)
│   ├── seed_data.py                 # Generate synthetic GST data via Faker
│   ├── descriptions.json            # Column-level descriptions for LLM context
│   └── connection.py                # SQLAlchemy engine factory
├── core/
│   ├── schema_extractor.py          # Reads DB metadata + descriptions.json → context string
│   ├── prompt_builder.py            # Assembles system prompt + schema + question
│   ├── llm_client.py                # Abstract LLM base + GroqClient implementation
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

**Status:** In progress — schemas received, seed data being written.

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

### Legacy Files (superseded)
The following files from the original toy schema are superseded but kept for reference:
- `database/schema.sql` — original 7-table SQLite schema (not used)
- `database/seed_data.py` — SQLite seed data (not used)
- `database/descriptions.json` — descriptions for old schema (not used)

---

## Phase 2: Core Pipeline (LLM Integration + Prompt Engineering)

**Goal:** NL question → LLM → SQL string.

### 2A. LLM Client (`core/llm_client.py`)

Abstract base class with provider implementations. Both Groq and OpenRouter use OpenAI-compatible APIs, so the client is a thin wrapper — just different base URLs and API keys.

```python
class LLMClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024) -> str:
        pass

class GroqClient(LLMClient): ...
class OpenRouterClient(LLMClient): ...
# Future: class VLLMClient(LLMClient): ... for local GPU
```

**Providers (free tiers only):**

| Provider | Free Tier Limits | Notes |
|----------|-----------------|-------|
| Groq | 30 RPM, 6K TPM, ~1,000 req/day | Fastest inference, model roster changes often |
| OpenRouter | ~20 RPM, ~200 req/day | More model variety, good fallback |

Spread evaluation load across both providers to work around daily limits.

**Models for comparison:**

Deployment candidates (must be ≤10B — future GPU can only handle this):
| Model | Params | Provider | Notes |
|-------|--------|----------|-------|
| `llama-3.1-8b-instant` | 8B | Groq | Primary candidate — API available now |
| `qwen/qwen3-coder:free` | ~8B | OpenRouter | Best free coding model |
| `XiYanSQL-QwenCoder-7B` | 7B | Local (vLLM) | Specialized SQL fine-tune, SOTA on BIRD (69%). Phase 5-B / Phase 6 only — no API available |

Upper-bound baseline (thesis comparison only — NOT for deployment):
| Model | Params | Provider | Notes |
|-------|--------|----------|-------|
| `llama-3.3-70b-versatile` | 70B | Groq | Shows how close ≤10B gets to 70B |

**Note:** Free tier models change frequently. Check provider docs before each eval run. The abstract LLMClient makes switching trivial — just change config.

**Rate limiting:** Implement simple sleep-based limiter per provider. Critical during batch evaluation.

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

Rules:
- Output ONLY the SQL query, no explanations
- Use only SELECT statements
- For intra-state: use CGST + SGST. For inter-state: use IGST
- return_period is MMYYYY format (e.g., '032026' for March 2026)
- "total tax" = cgst_amount + sgst_amount + igst_amount + cess_amount
- Qualify ambiguous columns with table aliases
- Use standard SQL compatible with SQLite

DATABASE SCHEMA:
{ddl_statements}

COLUMN DESCRIPTIONS:
{column_descriptions}

SAMPLE DATA:
{sample_rows}

USER: {question}
```

**Start zero-shot** (saves tokens on Groq free tier). Few-shot configurable for ablation in Phase 5.

**Prompt structure (beyond rules):** System prompt includes four explicit sections before the DDL — TABLE RESPONSIBILITIES (what each table stores), COLUMN OWNERSHIP (which table each key column belongs to), FOREIGN KEY RELATIONSHIPS, and COMMON JOIN PATTERNS. This was added after observing that 8B models consistently misattribute tax columns (cgst_amount etc.) to `invoices` instead of `invoice_items`, causing 3-attempt failures. The explicit mapping generalises across all query types, not just tax queries.

**Token behavior:** LLM APIs are stateless — every call must include the full context. The system prompt (~10K tokens) is sent with every query; there is no "send once" mechanism. Groq mitigates this with **implicit prefix caching**: identical system prompts are cached server-side, so repeated calls with the same schema context don't incur full compute cost. For the Streamlit UI, conversation history is accumulated across turns (system sent once, then user/assistant pairs grow) so within a chat session the schema is not re-sent redundantly.

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
- `groq` (Groq SDK)
- `openai` (OpenRouter uses OpenAI-compatible API)
- `sqlalchemy`
- `python-dotenv`
- `pydantic`

### Verification
```python
from core.sql_generator import SQLGenerator
sql = generator.generate("How many invoices are there?")
print(sql)  # Should output: SELECT COUNT(*) FROM invoices
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
- SQLite opened in read-only mode (`?mode=ro`)

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
|  [Chart tab] (bar chart if applicable)             |
|  Execution time: 45ms | Attempts: 1               |
+--------------------------------------------------+
|  Type your question...                    [Send]   |
+--------------------------------------------------+
```

### Key Implementation Details
- `st.chat_input` + `st.chat_message` for chat UX
- `@st.cache_resource` for pipeline init (expensive)
- `st.session_state` for chat history
- Response in tabs: SQL | Results | Chart
- Sidebar example questions (clickable):
  - "What is the total tax collected by each state?"
  - "Show the top 10 suppliers by taxable value"
  - "Monthly trend of B2B invoice count?"
  - "Which HSN codes have the highest IGST collection?"
  - "How many export invoices were filed in Q1 2026?"
  - "Average invoice value for 18% tax rate items?"
  - "List suppliers who filed more than 100 invoices"
  - "Compare CGST vs IGST collection across all months"

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
| Baseline | llama-3.1-8b, 0-shot, descriptions=ON, sample_rows=ON, max_attempts=3, temp=0.0 | Core result — establishes accuracy before RAG |

~130 API calls total. Results saved to `evaluation/results/baseline.csv`.

The baseline result feeds directly into Phase 5-B as the "before RAG" number. The primary thesis comparison is **baseline (static prompt) vs RAG pipeline**.

**Deferred (resume when API constraints lift or when needed):**
- Model ablations: qwen3-coder, llama-3.3-70b upper bound
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
python evaluation/benchmark.py --model llama-3.1-8b-instant --output evaluation/results/
# Generates CSV with per-question results and summary metrics
```

---

## Phase 5-B: RAG Enhancement (Branch: `rag-enhancement`)

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

### 5B-6. XiYanSQL-QwenCoder-7B (When GPU Available)

This is the specialized Text-to-SQL model recommended by the guide. Available on HuggingFace: `XGenerationLab/XiYanSQL-QwenCoder-7B-2502`.

- **BIRD benchmark**: 69.03% execution accuracy (SOTA for single fine-tuned model ≤7B)
- **Dialects**: SQLite, PostgreSQL, MySQL — all supported
- **Inference**: vLLM with bfloat16, requires ~10GB VRAM
- **Prompt format**: XiYanSQL uses its own prompt template (Chinese-language prompt shown in guide — adapt to English for GST use case)

Add `VLLMClient` to `core/llm_client.py` (OpenAI-compatible endpoint via vLLM server):
```python
class VLLMClient(LLMClient):
    def __init__(self, base_url: str, model: str)  # points to local vLLM server
```

**Run when GPU is available:**
```bash
vllm serve XGenerationLab/XiYanSQL-QwenCoder-7B-2502 \
  --dtype bfloat16 --gpu-memory-utilization 0.85
```

---

### 5B-7. RAG Evaluation

**Active (run now):** Single RAG run, same 100 questions as Phase 5 baseline.

| Run | Config | Purpose |
|-----|--------|---------|
| RAG pipeline | Schema RAG + Few-shot RAG, llama-3.1-8b, max_attempts=3, temp=0.0 | Core RAG result |

~130 API calls. Results saved to `evaluation/results/rag.csv`.

**Primary thesis comparison:** `baseline.csv` vs `rag.csv` — does RAG improve accuracy on GST domain?

**Deferred RAG ablations (resume when ready):**
- Schema RAG only vs Few-shot RAG only vs Both
- Top-K=3 vs Top-K=5 retrieved tables
- Q-SQL store size: 10 vs 25 vs 50 pairs
- RAG + llama-3.1-8b vs RAG + XiYanSQL-7B (needs GPU)

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

### 6A. Database Migration
- Switch SQLite → PostgreSQL
- Create read-only role for the pipeline
- Connection pooling via SQLAlchemy pool_size or PgBouncer

### 6B. API Backend
- FastAPI wrapper around `core/pipeline.py`
- `POST /query` → `{question, model}` → `{sql, data, row_count, execution_time}`
- Govt website calls this via REST/AJAX

### 6C. Local GPU (When Available)
- `VLLMClient` already added in Phase 5-B branch — merge into main
- Primary model: `XiYanSQL-QwenCoder-7B` (`XGenerationLab/XiYanSQL-QwenCoder-7B-2502`) — specialized Text-to-SQL, SOTA on BIRD (69% EX), supports SQLite/PostgreSQL/MySQL
- Serve via vLLM: `vllm serve XGenerationLab/XiYanSQL-QwenCoder-7B-2502 --dtype bfloat16`
- Change config: `llm_backend = "vllm"`, `default_model = "XiYanSQL-QwenCoder-7B"`

### 6D. Security
- Audit logging: log every query (question, SQL, result count, user ID)
- Per-IP rate limiting via `slowapi`
- Prompt injection defense (sanitize user input)
- HTTPS at reverse proxy (nginx)

### 6E. Caching
- Hash-based query cache (exact match on normalized question)
- Reduces LLM API calls for repeated questions

### 6F. Hindi/Regional Language Support (Future)
- Modify system prompt to accept Hindi/Hinglish questions
- Or add translation preprocessing step
- Qwen models have multilingual capability

---

## Timeline

| Week | Phase | Milestone | Branch |
|------|-------|-----------|--------|
| 1 | Phase 1 (original) ✅ | SQLite toy schema + seed data — superseded | `main` |
| 2 | Phase 2 ✅ | LLM generates SQL from natural language via Groq | `main` |
| 3 | Phase 3 ✅ | Full pipeline: question → validated SQL → results | `main` |
| 4 | Phase 4 ✅ | Streamlit demo built | `main` |
| Now | Phase 1 (redo) 🔄 | Official schemas (EWB, GSTR-3B, GSTR-7) + PostgreSQL toy data | `main` |
| Next | Phase 1 (redo) | 4th schema + update prompts/descriptions for new tables | `main` |
| TBD | Phase 5 | Gold Q-SQL pairs for official schemas + baseline evaluation | `main` |
| TBD | Phase 5-B | RAG branch: FAISS index, retriever, RAG pipeline + RAG evaluation | `rag-enhancement` |
| TBD | Ablations | All deferred ablation studies — resume when API constraints lift | `main` / `rag-enhancement` |
| TBD | Phase 6 | FastAPI + security hardening (when green light) | `main` (merge) |

---

## Dependencies (`requirements.txt`)

```
# Core
groq>=0.9.0
openai>=1.0
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
| Provider drops/changes free tier models | LLM client is abstract — switch provider or model in config |
| ≤10B models underperform on complex JOINs | Self-correction handles many failures. Document as thesis finding |
| Daily request limits slow evaluation | Spread across Groq + OpenRouter. ~1,200 combined req/day is enough for one full eval run |
| Official schemas too large for prompt | 19+ tables with dense column comments. RAG (Phase 5-B) is the natural fix — retrieve only relevant tables per query. Static prompt approach requires careful column pruning (use LLM-HIDE annotations). |
| Schema complexity: padded strings, quoted columns, VARCHAR dates | Document in descriptions_official.json as explicit LLM instructions (TRIM, TO_DATE, double-quote). Test with representative queries. |
| 4th schema not yet received | Build pipeline to be modular — add new schema/descriptions without touching core pipeline |
| No GPU when thesis is due | Groq is primary path. XiYanSQL + vLLM is Phase 5-B/6 — thesis passes without it |
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

### Schema Pivot (Phase 1 redo)
The original 7-table SQLite toy schema (`database/schema.sql`) is superseded by the official government schemas. Files kept for reference but not used by the pipeline. The pipeline itself (Phases 2–4 code) is database-agnostic — only `database/connection.py`, `config/settings.py`, `config/prompts.py`, and `database/descriptions_official.json` need updating for the new schemas.

---

## Thesis Contribution Framing

1. **Domain-specific Text-to-SQL for Indian GST data** — novel application domain, no prior work
2. **Schema enrichment via column descriptions** — quantified through ablation study
3. **Self-correction for open-source models** — demonstrates iterative error feedback value
4. **Multi-model comparison under constraints** — practical comparison of sub-10B vs larger models on domain-specific data
5. **RAG-augmented pipeline** (Phase 5-B) — Schema RAG + Few-shot RAG using FAISS; quantifies accuracy gain over static prompting on a domain-specific schema
6. **Deployment architecture** — full pipeline from demo to government-deployable API
