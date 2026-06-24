# Phase 5-B — RAG Enhancement: Detailed Implementation Plan

**Branch:** `rag-enhancement` · **Base:** `main` (untouched) · **Status:** dataset authoring (Part A)

This is the complete execution plan for the RAG phase. The high-level roadmap lives in `plan.md`
(§ Phase 5-B); this file is the detailed, authoritative implementation spec.

---

## 1. Context & Motivation

The static-prompt baseline on the frozen 112-question gold set (`evaluation/test_questions.json`)
scores **EX 90.2% ± 0.0, VER 97.6% ± 0.5** (runs=3, on `main`, in `evaluation/results/baseline.csv`).

Triage (committed `9c135db`) established that the residual failures are a **static-prompt ceiling**,
not pipeline bugs, and that *prose cannot move them*:

| Residual | Failure | Why prose failed |
|---|---|---|
| **Decode-join resistance** (headline) | Model *derives* GSTR-3B FY/quarter from the period column (`TO_CHAR(TO_DATE(ret_period,...))`, hallucinated `fp`, calendar≠financial year) instead of JOINing `common.mst_fy_years_t` / `mst_3bd_months_t`. | A forceful "labels need the decode JOIN" rule gave **0 EX gain** (decode category stuck at 25%) and caused a routing regression → reverted. |
| **Name-collision** | "were cancelled" → `canceldet` event log vs `tbl_ewb_parta_ewb.status='CNL'`. | Five layers of prose; phrasing-sensitive. |
| **Column/entity traps** | #48 `igst_tx` (GSTR-7 col) pulled into a 3B question; #97 groups by `deductee_name` (not unique) instead of `gstin_ded`. | Inconsistent under prose. |

**Hypothesis (to be tested, not assumed):** based on the observed error patterns, **few-shot
demonstration** is *expected* to contribute more to fixing these residuals than schema retrieval,
because they are behavior/column errors that a worked example shows directly. This is a hypothesis —
the 2×2 ablation (§9) decides it experimentally; the plan does not presuppose the outcome.

**Thesis question:** *Does RAG (schema retrieval + few-shot retrieval) improve Text-to-SQL accuracy
on a domain-specific GST schema, and which retrieval design choices matter?* — measured as
**baseline vs RAG on the identical 112-question eval set** (`baseline.csv` vs `rag.csv`), plus an
**intrinsic retrieval-quality study** (§3.5) over embedding model, semantic-vs-hybrid retrieval, and
category-aware reranking.

---

## 2. Methodology — train/test split & leakage control

**The eval set (112) is frozen as the held-out test set.** Both baseline and RAG are scored on it.
Because the baseline is already measured on these exact 112, the comparison needs **no baseline re-run**.

**The few-shot / RAG retrieval pool must be DISJOINT from the 112.** If the pool contains an eval
question (or a near-paraphrase), the retriever hands the model the gold SQL → trivially inflated,
non-generalizing, deployment-irrelevant numbers.

**Fairness comes from pool *coverage*, not inclusion.** For every eval question, the pool must
contain a *different* question of the *same pattern* (another decode-join, another tax-payable
ranking). Then RAG retrieves a genuinely relevant demonstration without ever seeing the test item.
This measures true generalization — the only number meaningful for production. (Same principle as
Spider/BIRD train vs test.)

**Leakage guard (mandatory, scripted & saved → `evaluation/leakage_audit.py`):**
1. No exact question/SQL duplicate vs the 112. ✅ (0)
2. Embed all pool + eval questions with the retrieval model; report two signals:
   - **Question cosine > 0.90** — semantic near-paraphrase. NOTE: on this short, single-domain
     question set `bge-large` compresses same-*template* questions high (max observed 0.9747, mean
     ~0.88), so cosine alone over-counts — it flags intended same-pattern *coverage*, not leakage.
   - **SQL template-twin** — gold SQL identical *after masking literals* (numbers/strings). This is
     the operative leak test: a twin means the model could copy the answer by swapping one constant.
     **Required = 0.** Achieved by rewording the borderline twins (different metric/grain/shape, not
     just a literal swap). Result: 62 cosine-flags (documented benign), **0 SQL template-twins = PASS**.
   Report persisted to `evaluation/results/leakage_audit.csv`.

---

## 3. Architecture — what changes vs what is reused

**Only prompt assembly becomes per-question.** Everything downstream is reused unchanged. RAG ships
as **subclasses**; base classes on `main` are not edited.

```
                         BASELINE                          RAG (subclass)
question ─▶ PromptBuilder.build_messages (STATIC      ─▶ RAGPromptBuilder.build_messages (DYNAMIC:
            system prompt built once in __init__)         retrieve tables+few-shots per question)
        ─▶ SQLGenerator.generate ─────────────────────────────  (reused as-is)
        ─▶ run_with_correction (validate→execute→self-correct) (reused as-is)
```

Integration points confirmed in code:
- `core/prompt_builder.py` — `PromptBuilder.build_messages(question)` returns `[system, user]`;
  the system prompt is cached in `__init__`. `RAGPromptBuilder` overrides `build_messages` to build
  it per question. `build_correction_messages` is inherited unchanged (it appends the error turn to
  `prior_messages`, which already carry the RAG system prompt).
- `core/sql_generator.py` — `SQLGenerator(llm, prompt_builder)` calls `prompt_builder.build_messages`.
  Works with any builder exposing that method. No change.
- `core/pipeline.py` — `TextToSQLPipeline.__init__` wires extractor→`PromptBuilder`→`SQLGenerator`;
  `ask()` calls `run_with_correction`. `RAGTextToSQLPipeline` overrides only `__init__`; `ask()` is
  inherited.
- `core/schema_extractor.py` — `SchemaExtractor` already iterates `self._tables` and has per-table
  DDL + `descriptions_official.json` (`table_description`, `columns`, FK logic in `get_ddl`). Reuse it
  to produce per-table M-Schema blocks.
- `evaluation/benchmark.py` — `run()` / `_score_once()` / metrics are pipeline-agnostic; only the
  pipeline instantiation (currently `TextToSQLPipeline(settings)` at line ~61) needs a branch.

---

## 3.5. Evaluation layers — intrinsic vs extrinsic (the cost-control principle)

The expanded design space (multiple embedding models, semantic vs hybrid, category-aware
reranking, always-core on/off) would be a combinatorial explosion of end-to-end EX runs — each
~130 LLM calls × `runs=3` through the flaky HPC tunnel ([[project_tunnel_flaky]]). To keep it
affordable **and** scientifically cleaner, evaluation is split into two layers:

**Layer 1 — Intrinsic retrieval quality (CPU-only, no LLM, no tunnel, fully deterministic).**
Run *every* retriever variant here. Metrics computed against the 112 eval questions using the
hand-labeled `category`/`module` as relevance signals:
- **Recall@k / same-pattern hit-rate** — does retrieval fetch a same-category (and, for schema,
  same-module + `common.mst_*` for decode) demonstration in the top-k?
- **Leakage cosine** — max pool↔eval cosine (must stay ≤ 0.90, §2).
- **Prompt-token count** and **retrieval latency** — efficiency, free byproducts.

This layer selects the **winning retriever config** (embed model, semantic-vs-hybrid, category
weight) *before* spending any HPC budget. It is itself a thesis results section (IR-style intrinsic
evaluation is standard).

**Layer 2 — Extrinsic / end-to-end EX (expensive: HPC + tunnel).**
Run *only* for the winning retriever config **and** the 2×2 ablation cells (§9). Do **not** run a
full EX sweep for every retriever variant — Layer 1 already ranked them.

> **Note on the eval-question category label:** it is *gold annotation*, not available at deployment.
> Any category-aware retrieval (§5.2, suggestion #7) must therefore either **predict** the category
> from the question text, or be reported explicitly as an **oracle upper bound** — never silently use
> the gold label as if it were a deployment signal.

---

## 4. Part A — Disjoint retrieval pool

**File:** `evaluation/rag_qsql_store.json` (tracked; NOT under `evaluation/results/` which is
gitignored). Item shape identical to `test_questions.json`:
`{id, module, difficulty, category, question, gold_sql[, order_matters]}`. **IDs start at 1001** to
visibly separate pool from eval (1–112).

### 4.1 Stratified spec (target ~140, coverage ≥ eval, failure-modes over-weighted)

| category | eval n | pool target | EWB / 3B / GSTR-7 split | rationale |
|---|---|---|---|---|
| decode | 4 | 15 | 0 / 15 / 0 | THE failure mode — dense decode-join demos |
| ranking | 14 | 20 | 7 / 7 / 6 | name-by-key, ties, top-N |
| domain_specific | 22 | 24 | 8 / 8 / 8 | tax-payable / TDS column traps |
| aggregation | 30 | 22 | 8 / 7 / 7 | already strong; modest |
| grouping | 18 | 16 | 5 / 6 / 5 | |
| join | 12 | 12 | 5 / 0 / 7 | (3B doesn't join except decode) |
| filtering | 9 | 10 | 4 / 3 / 3 | |
| quirk | 4 | 8 | 4 / 3 / 1 | `"InvVal"`, `travdist` cast, timestamps, `"range"`, `"current_date"`, `fil_dt` TO_DATE |
| subquery | 2 | 8 | 3 / 3 / 2 | too thin in eval to retrieve against |
| having | 1 | 5 | 1 / 2 / 2 | too thin in eval |
| **total** | 112 | **~140** | ~45 / ~54 / ~41 | mirrors eval module mix |

### 4.2 Authoring rules
- Author questions that are **different** from the 112 (different entities/periods/columns/
  combinations/phrasings) but exercise the **same pattern**.
- Ground SQL in the **verified column names & data values** (probe `gst_official` first:
  `/tmp/schema_probe.py`) — avoids a mass verify-fix loop.
- Ranking golds → **minimal entity projection** (the convention now in `test_questions.json`).
- **Decode demos explicitly JOIN** `common.mst_fy_years_t` (flag_fy=fy_flag → desc_year) /
  `mst_3bd_months_t` (ret_period_fl=ret_period → month_desc/quarter) — this is the behavior RAG must teach.
- Tax-payable demos use the correct module columns (3B: `iamt/camt/samt/csamt`; GSTR-7 TDS:
  `iamt+camt+samt`, base = `amt_ded`; GSTR-7 tax_pay: `*_tx`).

### 4.3 Verification (every pair)
Execute each `gold_sql` on `gst_official`; require **no error and non-empty result** — same bar as
the 112, reusing the execute-check pattern from `/tmp/apply_gold_fixes.py`. Fix failures, re-run.

---

## 5. Part B — Components (detailed)

### 5.1 `core/schema_indexer.py` (new)
M-Schema per table → embed → FAISS.
```python
class SchemaIndexer:
    def __init__(self, extractor: SchemaExtractor, embed_model, index_dir: str): ...
    def build_index(self) -> None        # writes index/schema.faiss + index/tables.pkl
    def load(self) -> None
    def retrieve_tables(self, question: str, k: int) -> list[str]   # top-k M-Schema blocks
```
- Add `SchemaExtractor.get_table_blocks() -> dict[str, str]` (reuses existing per-table column/FK
  logic) so M-Schema generation doesn't duplicate code.
- **M-Schema block format** (one per table, embedded as a unit):
  ```
  Table: live_reports.r3b_comphrehensive_list_mv_upd1_t_partitioned — GSTR-3B monthly summary return…
    gstin (varchar) -- taxpayer GSTIN
    fy_flag (int) -- financial-year flag & partition key; JOIN common.mst_fy_years_t for desc_year
    osup_det_txval (numeric) -- outward taxable value (3.1a)
    samt/camt/iamt/csamt (numeric) -- tax payable rollups
    ...
  ```

### 5.2 `core/rag_retriever.py` (new)
```python
class RAGRetriever:
    def __init__(self, settings): ...                 # loads embed model ONCE
    def retrieve_tables(self, q: str, k: int) -> list[str]      # via SchemaIndexer
    def retrieve_fewshots(self, q: str, k: int) -> list[dict]   # via qsql FAISS over rag_qsql_store.json
    def retrieve(self, q: str) -> dict                          # {"tables": [...], "fewshots": [...]}
```
- One `SentenceTransformer` load shared by both indexes.
- qsql index built from `evaluation/rag_qsql_store.json` — **dense vector embeds the `question` only**
  (kept symmetric with the query, which is also question-only; do NOT embed pool SQL/structure into
  the dense vector — that asymmetry hurts). Structure/category enter via the hybrid + rerank signals
  below, not the embedding (resolves suggestions #3/#8).

**Retrieval mode is configurable (`settings.rag_retrieval_mode`):**
- `semantic` — FAISS cosine only (baseline retriever).
- `hybrid` — **RRF / weighted fusion of dense (FAISS) + lexical (BM25 over question text)**
  (suggestion #2). Lexical catches exact GST jargon the residuals hinge on — "cancelled", "quarter",
  "FY", `decode` terms — that pure embedding can miss. BM25 over `rank_bm25` (tiny, 140 short docs).
  Default fusion: RRF (rank-based, no weight tuning); weighted (`0.6·dense + 0.4·lexical`) as a knob.
- **Category-aware rerank (optional, `settings.rag_category_weight > 0`, suggestion #7):** after
  fusion, boost candidates whose pool `category` matches the **predicted** question category. Category
  is predicted from the question (cheap heuristic/keyword classifier), **not** read from eval gold
  (see §3.5 oracle note). Report predicted-vs-oracle as a sensitivity check.

All retrieval is **deterministic** (suggestion #11): FAISS `IndexFlatIP` (exact), fixed `np` seed,
stable tie-break by ascending `id`. Same query ⇒ same retrieved set, every run.

### 5.3 `config/prompts.py`
- Factor the shared general header (Rules + HOW-TO-BUILD playbook + GST DOMAIN RULES + quoting/date
  conventions) out of `SYSTEM_PROMPT_TEMPLATE` so baseline and RAG share it verbatim (no divergence).
- Add `RAG_SYSTEM_PROMPT_TEMPLATE` = shared header + placeholders `{retrieved_schema}` and
  `{retrieved_fewshots}` **instead of** the full `{ddl}/{descriptions}/{sample_rows}` dump.

**RAG system prompt structure:**
```
[Rules + HOW-TO-BUILD playbook + GST DOMAIN RULES + quoting/date conventions]   (general, static)

RELEVANT TABLES (retrieved):
{top-k M-Schema blocks  +  always-included 3 MAIN tables}

SIMILAR SOLVED EXAMPLES (retrieved):
Q: …  SQL: …
Q: …  SQL: …
```

### 5.4 `core/prompt_builder.py`
```python
class RAGPromptBuilder(PromptBuilder):
    def __init__(self, retriever: RAGRetriever, settings): ...   # no static schema dump
    def build_messages(self, question: str) -> list[dict]:
        r = self._retriever.retrieve(question)
        system = RAG_SYSTEM_PROMPT_TEMPLATE.format(
            retrieved_schema=_join(r["tables"] + always_core),
            retrieved_fewshots=_format(r["fewshots"]),
        )
        return [{"role": "system", "content": system},
                {"role": "user", "content": USER_PROMPT_TEMPLATE.format(question=question)}]
```
- `--rag-mode fewshot` → `retrieve_tables` is skipped and the **full static schema** is used
  (cheap-signal variant); `schema`/`both` use retrieved tables.

### 5.5 `core/pipeline.py`
```python
class RAGTextToSQLPipeline(TextToSQLPipeline):
    def __init__(self, settings):
        # engine + allowed_tables as base; build RAGRetriever + RAGPromptBuilder + SQLGenerator
        # ask() inherited (run_with_correction unchanged)
```

### 5.6 `config/settings.py` (new fields)
```python
embed_model: str = "BAAI/bge-large-en-v1.5"   # challenger: BAAI/bge-m3 (intrinsic compare, §3.5/#1)
rag_top_k_tables: int = 5
rag_top_k_fewshots: int = 3
rag_index_dir: str = "index"
qsql_store_path: str = "evaluation/rag_qsql_store.json"
rag_always_include_core_tables: bool = True    # ABLATION on/off (#6) — not assumed; see §9
rag_retrieval_mode: str = "semantic"           # "semantic" | "hybrid" (BM25+RRF, #2)
rag_hybrid_dense_weight: float = 0.6           # used only if weighted fusion (vs RRF) chosen
rag_category_weight: float = 0.0               # >0 enables category-aware rerank (#7); 0 = off
rag_embed_seed: int = 0                         # determinism (#11)
rag_trace_path: str = "evaluation/results/rag_traces.jsonl"   # per-question retrieval traces (#10)
```

### 5.7 `evaluation/benchmark.py`
- `--rag` flag + `--rag-mode {fewshot,schema,both}` → instantiate `RAGTextToSQLPipeline` instead of
  `TextToSQLPipeline`. Core scoring (`run`, `_score_once`, EX/VER/EM, `--runs`, summary) reused verbatim.
- **Retrieval traces (#10, build in from day 1):** when `--rag`, append one JSONL row per eval
  question to `settings.rag_trace_path` — `{id, question, retrieved_tables, retrieved_fewshot_ids,
  predicted_category, generated_sql, gold_sql, exec_rowcount, ex, ver, attempts}`. Powers the Error
  Analysis chapter ("why did RAG fix #41" → read the trace).
- **Efficiency metrics (#9, mostly free):** per question also log `prompt_tokens` (system+user),
  `retrieval_latency_ms`, `inference_latency_ms`; summary reports mean prompt-tokens & latency per
  config so the thesis discusses accuracy *and* cost (baseline full-schema vs retrieved-schema).

### 5.9 `evaluation/intrinsic_eval.py` (new, Layer-1 / §3.5)
CPU-only, no LLM. For a given retriever config, computes recall@k / same-category hit-rate / leakage
cosine / mean prompt-tokens over the 112 eval questions and writes `evaluation/results/intrinsic_<cfg>.csv`.
Drives the embed-model (#1) and semantic-vs-hybrid (#2) selection **before** any HPC run.

### 5.8 `requirements.txt` / `.gitignore`
- Add (Phase 5-B): `sentence-transformers>=2.7`, `faiss-cpu>=1.8`, `rank_bm25>=0.2` (hybrid, #2) —
  then `pip freeze` to pin actual versions (CLAUDE.md rule).
- `.gitignore`: add `index/` (FAISS files, regenerable). `rag_qsql_store.json` stays **tracked**.
  `evaluation/results/` already gitignored → traces (`rag_traces.jsonl`) + intrinsic CSVs land there.

---

## 6. Part C — Implementation & evaluation order (intrinsic-first, then cheap extrinsic signal)

1. **Author + verify the pool** (`rag_qsql_store.json`) → run leakage audit. ⟵ *current step*
2. **Install deps** (`sentence-transformers`, `faiss-cpu`, `rank_bm25`); gitignore `index/`.
3. **`RAGRetriever` + qsql index** (few-shot side): semantic + hybrid (BM25/RRF) + optional category rerank.
4. **Layer-1 intrinsic eval (§3.5, CPU-only):** `intrinsic_eval.py` over {bge-large vs bge-m3} ×
   {semantic vs hybrid} (± category weight). Pick the **winning retriever config** by recall@k /
   same-category hit-rate / leakage / prompt-tokens. **No HPC spend yet.**
5. **`RAGPromptBuilder` + `RAGTextToSQLPipeline` + `RAG_SYSTEM_PROMPT_TEMPLATE` + settings + benchmark
   `--rag` + trace/efficiency logging.**
6. **Extrinsic cheap signal — few-shot RAG only** (full static schema + retrieved few-shots, winning
   retriever): `benchmark.py --rag --rag-mode fewshot --runs 3 --output evaluation/results/rag_fewshot.csv`.
   *Hypothesis* (§1, not assumed): few-shot moves the documented residuals more than schema retrieval —
   the 2×2 (§9) tests it. Compare vs `baseline.csv`.
7. **`SchemaIndexer` + schema FAISS**; wire retrieved tables into the prompt (`both` mode).
8. **2×2 ablation cells (§9), all real runs (#12):** schema-only **and** full RAG —
   `--rag-mode schema` / `--rag-mode both`, `--runs 3`. `both` → `evaluation/results/rag.csv` (headline).
9. **Always-core on/off (#6):** rerun the winning mode with `rag_always_include_core_tables` toggled —
   measure whether injecting all 3 MAIN tables helps or adds cross-module confusion.
10. **Deferred (§ "Deferred items"):** reranker (#4), dynamic-k (#5), structural index (#8),
    pool-size sweep (#13), top-K table sweep.

---

## 7. Risks & mitigations

| Risk | Mitigation |
|---|---|
| **Leakage** pool↔eval | Disjoint pool + cosine>0.90 audit (saved). |
| Retrieval fetches wrong tables (only 21 tables) | `rag_always_include_core_tables` → always inject the 3 MAIN tables regardless of retrieval. |
| Embed model load cost | Load once per `RAGRetriever`; `@st.cache_resource` in UI; module-level in eval. |
| Flaky HPC tunnel ([[project_tunnel_flaky]]) | Health-check `curl -m5 localhost:8765/v1/models` before any benchmark; re-open tunnel, never touch HPC jobs. |
| Index drift after schema change | `index/` gitignored + regenerated by `SchemaIndexer.build_index()` on demand. |
| Scope creep / overfitting | No further static-prompt tuning; demos are general patterns, not eval answers. |
| **Combinatorial EX-run blowup** (new design space × HPC tunnel) | **Intrinsic/extrinsic split (§3.5)** — variant selection on CPU; HPC only for the winner + 2×2 cells. |
| **Oracle leakage via gold category** (#7) | Category is *predicted* from the question at inference, or reported as an explicit oracle upper bound — never the eval gold label silently. |
| **Embedding query/doc asymmetry** (#3/#8) | Dense vector embeds question text only (symmetric); structure/category enter via hybrid + rerank, not the embedding. |
| Non-reproducible retrieval (#11) | Exact FAISS (`IndexFlatIP`), fixed seed, stable id tie-break — same query ⇒ same set. |

---

## 8. Verification

- **Retrieval sanity:** decode question → `retrieve_fewshots` returns decode-join demos, `retrieve_tables`
  returns 3B + `common.mst_*`; GSTR-7 question → r7 tables. Spot-check 3–4 across modules.
- **Leakage audit passes** (no exact/near-dup) — report saved.
- **End-to-end:** `python evaluation/benchmark.py --rag --rag-mode both --runs 3 --output evaluation/results/rag.csv`
  runs clean against tunneled vLLM.
- **Intrinsic (Layer 1, §3.5):** `intrinsic_eval.py` runs CPU-only; recall@k / same-category hit-rate
  reproducible across runs (determinism, #11); winning retriever config picked before any HPC spend.
- **Traces (#10):** `rag_traces.jsonl` has one row per eval question with retrieved tables/few-shots +
  generated/gold SQL — spot-check a fixed residual (e.g. a decode question) shows a decode-join demo.
- **Primary result:** the 2×2 (§9) — all four cells filled; `rag.csv` (full RAG) EX vs `baseline.csv`
  EX (90.2%), by-category breakdown confirms `decode`/`ranking` improve; `rag_fewshot.csv` +
  schema-only cell isolate each component's lift.
- **Base untouched:** `git diff main -- core/pipeline.py core/prompt_builder.py core/sql_generator.py`
  shows only additions (subclasses), no edits to base classes.

---

## 9. Thesis deliverables

**Primary — the 2×2 component ablation (#12, all cells are real runs, none left blank):**

| Configuration | Retrieved schema | Few-shot | EX | VER | mean prompt-tokens |
|---|---|---|---|---|---|
| Baseline | Full static schema | No | 90.2% | 97.6% | ~20.1k (full schema) |
| Schema-retrieval only | Retrieved | No | | | |
| Few-shot only | Full static schema | Yes | **94.6%** | **100.0%** | ~20,103 (approx) |
| Full RAG | Retrieved | Yes | | | |

**Few-shot RAG run (2026-06-25, runs=3, bge-large + retrieval=semantic, k=3):** EX 94.6% ±0.0,
VER 100% ±0.0. By category: **decode 25%→100% (+75, the headline residual — fixed)**, having
67→100, ranking 79→93, domain 91→100; fixed 11 of 12 baseline failures; 0 invalid SQL. Net +4.4
= fixed 11, **regressed 5** (trace-diagnosed): #94/#96/#109 the `amt_ded` name-trap via retrieval
(nearest pool demos are *base-amount* `SUM(amt_ded)` → model copied the wrong column for "TDS
deducted" = `iamt+camt+samt`); #107 deductor/deductee grouping; #59 baseline leaned on a static
few-shot near-twin (RAG's disjoint pool is the more honest number); #62 decode-label-vs-raw fy_flag.
Regressions are pool-fixable with GENERAL demos (teach the TDS-sum column) + leakage re-audit — next loop.
Result in `evaluation/results/rag_fewshot.csv`; per-question traces in `rag_traces.jsonl`.

Isolates schema-RAG vs few-shot-RAG contributions instead of conflating them. Each cell also broken
down **by-category** and **by-difficulty** (confirm `decode`/`ranking` residuals improve).

**Secondary — intrinsic retrieval study (§3.5, Layer 1, CPU-only):**
- Embed-model comparison (`bge-large` vs `bge-m3`, #1) — recall@k / same-category hit-rate.
- Semantic vs hybrid (BM25+RRF, #2) — does lexical fusion recover the jargon-driven residuals?
- Category-aware rerank: predicted vs oracle (#7).

**Efficiency (#9):** prompt-tokens, retrieval latency, inference latency — Baseline vs Few-shot vs
Full RAG. Lets the thesis argue cost as well as accuracy (retrieved schema ≪ 26.5K static prompt).

**Narrative:** RAG closes the static-prompt ceiling (esp. decode-join), under leakage-controlled,
generalization-valid methodology; component ablation + intrinsic study justify the design choices.

## Deferred items (explicitly scoped out of the core run; "if time permits")
- **#4 Cross-encoder reranker** (`bge-reranker`) — top-10→top-3 rerank; add only if intrinsic eval
  shows a precision problem (pool is only ~140, hand-curated).
- **#5 Dynamic top-K** (similarity threshold) — hurts reproducibility, trivial token saving; fixed k kept.
- **#8 Structural / AST index** — same query/doc asymmetry as #3; hybrid (#2) + category (#7) cover most of it.
- **#13 Pool-size sensitivity** (20/50/100/140) — "does retrieval saturate?"; cheap subsample if time.
- **Top-K table sweep** (k=3 vs 5).

## 10. Configuration defaults (adjustable)
Pool ~140 · embed `BAAI/bge-large-en-v1.5` (challenger `bge-m3`) · retrieval `semantic` default,
`hybrid` (BM25+RRF) as measured ablation · k=5 tables / k=3 few-shots · always-include 3 MAIN tables
is an **ablation toggle, not an assumption** · retrieval deterministic (exact FAISS, fixed seed) ·
traces + efficiency metrics logged every RAG run.
