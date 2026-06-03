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

**Goal:** Create a GST-like relational schema in SQLite with synthetic data.

### Tables

**`suppliers`** (master data)
```sql
CREATE TABLE suppliers (
    supplier_id         INTEGER PRIMARY KEY,
    gstin               TEXT NOT NULL UNIQUE,       -- 15-char GST identification number
    legal_name          TEXT NOT NULL,
    trade_name          TEXT,
    state_code          TEXT NOT NULL,              -- 2-digit state code (e.g., '27' for Maharashtra)
    state_name          TEXT NOT NULL,
    registration_type   TEXT DEFAULT 'Regular',     -- Regular, Composition, etc.
    created_at          DATE NOT NULL
);
```

**`buyers`** (master data)
```sql
CREATE TABLE buyers (
    buyer_id            INTEGER PRIMARY KEY,
    gstin               TEXT,                       -- NULL for unregistered B2C buyers
    legal_name          TEXT,
    state_code          TEXT NOT NULL,
    state_name          TEXT NOT NULL,
    buyer_type          TEXT NOT NULL               -- 'B2B', 'B2CL', 'B2CS', 'EXPORT'
);
```

**`invoices`** (core transaction table — GSTR-1 Table 4/5/6/7)
```sql
CREATE TABLE invoices (
    invoice_id          INTEGER PRIMARY KEY,
    invoice_number      TEXT NOT NULL,
    invoice_date        DATE NOT NULL,
    invoice_type        TEXT NOT NULL,              -- 'B2B', 'B2CL', 'B2CS', 'EXPORT', 'CDNR', 'CDNUR'
    supplier_id         INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    buyer_id            INTEGER REFERENCES buyers(buyer_id),
    place_of_supply     TEXT NOT NULL,              -- state code where supply is made
    reverse_charge      BOOLEAN DEFAULT FALSE,
    invoice_value       REAL NOT NULL,              -- total invoice value including tax
    return_period       TEXT NOT NULL,              -- MMYYYY format e.g., '032026'
    filing_status       TEXT DEFAULT 'Filed'
);
```

**`invoice_items`** (line items with tax breakup)
```sql
CREATE TABLE invoice_items (
    item_id             INTEGER PRIMARY KEY,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(invoice_id),
    hsn_code            TEXT NOT NULL,              -- Harmonized System of Nomenclature
    description         TEXT,
    quantity            REAL,
    unit                TEXT,                       -- UQC: units like KGS, NOS, MTR
    taxable_value       REAL NOT NULL,
    tax_rate            REAL NOT NULL,              -- 0, 5, 12, 18, 28
    cgst_amount         REAL DEFAULT 0,             -- Central GST (intra-state)
    sgst_amount         REAL DEFAULT 0,             -- State GST (intra-state)
    igst_amount         REAL DEFAULT 0,             -- Integrated GST (inter-state)
    cess_amount         REAL DEFAULT 0
);
```

**`hsn_master`** (reference table)
```sql
CREATE TABLE hsn_master (
    hsn_code            TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    chapter             TEXT,                       -- first 2 digits
    default_tax_rate    REAL
);
```

**`state_codes`** (reference)
```sql
CREATE TABLE state_codes (
    state_code          TEXT PRIMARY KEY,
    state_name          TEXT NOT NULL,
    state_type          TEXT                        -- 'State', 'UT'
);
```

**`export_invoices`** (GSTR-1 Table 6 specifics)
```sql
CREATE TABLE export_invoices (
    export_id           INTEGER PRIMARY KEY,
    invoice_id          INTEGER NOT NULL REFERENCES invoices(invoice_id),
    port_code           TEXT,
    shipping_bill_no    TEXT,
    shipping_bill_date  DATE,
    export_type         TEXT NOT NULL               -- 'WITH_PAYMENT', 'WITHOUT_PAYMENT'
);
```

### Seed Data Strategy

`seed_data.py` generates:
- 50 suppliers across 10 Indian states
- 200 buyers (mix of B2B registered, B2C large, B2C small, export)
- 5,000 invoices across 12 months (enables time-series queries)
- 15,000 invoice items (avg 3 items per invoice)
- Realistic distributions: 80% intra-state (CGST+SGST), 20% inter-state (IGST)
- Tax rates following actual GST slabs: 0%, 5%, 12%, 18%, 28%
- HSN codes from real chapters (e.g., 8471 for computers, 6109 for T-shirts)
- Use `Faker` library with Indian locale for names/addresses

### Column Descriptions (`descriptions.json`)

Critical for LLM accuracy. Structure:
```json
{
  "invoices": {
    "table_description": "Contains all GST invoice records filed under GSTR-1 return.",
    "columns": {
      "invoice_type": "Type of supply: 'B2B' (business-to-business), 'B2CL' (B2C over 2.5 lakh), 'B2CS' (B2C small), 'EXPORT', 'CDNR' (credit note registered), 'CDNUR' (credit note unregistered)",
      "place_of_supply": "2-digit state code. Determines if IGST or CGST+SGST applies.",
      "return_period": "Filing period in MMYYYY format. E.g., '032026' = March 2026.",
      "reverse_charge": "TRUE if tax payable by buyer instead of seller (Section 9(3)/9(4) CGST Act)"
    }
  },
  "invoice_items": {
    "table_description": "Line items within each invoice. Tax breakup at item level.",
    "columns": {
      "cgst_amount": "Central GST. Non-zero only for intra-state supplies.",
      "sgst_amount": "State GST. Always equals CGST for intra-state supplies.",
      "igst_amount": "Integrated GST. Non-zero only for inter-state supplies or exports.",
      "taxable_value": "Value before tax. Tax is calculated on this amount.",
      "hsn_code": "Harmonized System code. First 2 digits = chapter, first 4 = heading."
    }
  }
}
```

### Files to Create
- `database/schema.sql`
- `database/seed_data.py`
- `database/descriptions.json`
- `database/connection.py`

### Libraries
- `sqlite3` (stdlib)
- `sqlalchemy`
- `Faker`

### Verification
```bash
# After running seed_data.py:
sqlite3 gst_demo.db "SELECT COUNT(*) FROM invoices;"
# Expected: ~5000
```

---

## Phase 2: Core Pipeline (LLM Integration + Prompt Engineering)

**Goal:** NL question → LLM → SQL string.

### 2A. LLM Client (`core/llm_client.py`)

Abstract base class + Groq implementation:
```python
class LLMClient(ABC):
    @abstractmethod
    def generate(self, messages: list[dict], temperature: float = 0.0, max_tokens: int = 1024) -> str:
        pass

class GroqClient(LLMClient):
    def __init__(self, api_key: str, model: str = "llama-3.1-8b-instant"):
        ...
```

**Models for comparison (all on Groq):**

Deployment models (must be ≤10B — future GPU can only handle this size):
| Model | Params | Notes |
|-------|--------|-------|
| `llama-3.1-8b-instant` | 8B | Primary — guaranteed on free tier, fits GPU constraint |
| `gemma2-9b-it` | 9B | Google's model, strong instruction following |

Upper-bound baseline (for thesis comparison only — NOT for deployment):
| Model | Params | Notes |
|-------|--------|-------|
| `llama-3.3-70b-versatile` | 70B | Shows how close ≤10B gets to a 70B model |

**Rate limiting:** Groq free tier = 30 RPM, 6K TPM. Implement simple token bucket with sleep.

### 2B. Schema Extractor (`core/schema_extractor.py`)

```python
class SchemaExtractor:
    def get_ddl(self) -> str                    # CREATE TABLE statements
    def get_sample_rows(self, table, n=3) -> str # Example rows for grounding
    def get_column_descriptions(self) -> str     # From descriptions.json
    def get_full_context(self) -> str            # Combined context block
```

Reads live DB schema via `sqlalchemy.inspect` — stays in sync if schema evolves.

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
- `groq`
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

### 5C. Thesis Experiments

| Experiment | Purpose |
|---|---|
| Llama 3.1-8B vs Gemma2-9B (deployable) vs Llama 3.3-70B (upper-bound baseline) | Model comparison (main thesis table) |
| With vs without column descriptions | Schema enrichment impact |
| With vs without sample rows | Data grounding impact |
| 0-shot vs 3-shot vs 5-shot | Few-shot learning effect |
| 1 attempt vs up to 3 (self-correction) | Error feedback loop value |
| Accuracy by difficulty level (simple/moderate/challenging) | Where models struggle |
| Temperature 0.0 vs 0.3 vs 0.7 | Decoding strategy impact |

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
- Add `VLLMClient` class in `llm_client.py`
- Serve Qwen2.5-Coder-7B via vLLM (OpenAI-compatible API)
- Change config: `llm_backend = "vllm"` instead of `"groq"`

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

| Week | Phase | Milestone |
|------|-------|-----------|
| 1 | Phase 1 | Database schema + seed data working |
| 2 | Phase 2 | LLM generates SQL from natural language via Groq |
| 3 | Phase 3 | Full pipeline: question → validated SQL → results |
| 4 | Phase 4 | Streamlit demo ready to show advisor |
| 5-6 | Phase 5 | Benchmark framework + initial accuracy numbers |
| 7-8 | Phase 5 | All ablation studies + model comparisons complete |
| 9-10 | Phase 6 | FastAPI + PostgreSQL + security (when green light) |

---

## Dependencies (`requirements.txt`)

```
# Core
groq>=0.9.0
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

# Production (Phase 6 — uncomment when needed)
# psycopg2-binary>=2.9
# fastapi>=0.111
# uvicorn>=0.30
# slowapi>=0.1
# vllm>=0.5
```

---

## Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Groq drops/changes free tier models | LLM client is abstract — switching is one config change |
| Llama 3.1-8B underperforms on complex JOINs | Self-correction handles many failures. Compare with larger models. Document as thesis finding |
| Rate limit (6K TPM) slows evaluation | 2s delay between eval queries. 100 questions = ~3.5 min |
| GST schema too big for prompt | 7 tables fit in ~3K tokens. Llama 3.1-8B has 128K context. Not a risk |
| No GPU when thesis is due | Groq is primary path. Local GPU is Phase 6 nice-to-have |
| SQL injection in govt deployment | Validator blocks non-SELECT + DB has read-only role. Defense in depth |

---

## Thesis Contribution Framing

1. **Domain-specific Text-to-SQL for Indian GST data** — novel application domain, no prior work
2. **Schema enrichment via column descriptions** — quantified through ablation study
3. **Self-correction for open-source models** — demonstrates iterative error feedback value
4. **Multi-model comparison under constraints** — practical comparison of sub-10B vs larger models on domain-specific data
5. **Deployment architecture** — full pipeline from demo to government-deployable API
