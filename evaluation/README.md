# Evaluation — How We Test the Model

This document explains **how** we measure the Text-to-SQL pipeline, **what** the
metrics mean, and **what counts as a good score**.

---

## 1. The core idea

We never grade the SQL *text* by eye. We grade it by **what it returns**.

For every test item we have a **gold** (reference) question + a hand-written,
DB-verified SQL answer. To score the model we:

```
question ──► pipeline (XiYanSQL-7B) ──► predicted SQL ──► run on gst_official ──► predicted rows
                                                                                      │
gold SQL ───────────────────────────────────────────► run on gst_official ──► gold rows
                                                                                      │
                                                                          compare rows ──► metrics
```

So "correct" means **the predicted query produces the same answer as the gold
query**, even if it's written differently. This is the standard approach in the
Text-to-SQL literature (Spider, BIRD).

Files:
- `test_questions.json` — the gold set (question + gold SQL + difficulty/module tags)
- `metrics.py` — the three metrics
- `benchmark.py` — runs the whole set and writes `results/baseline.csv` + a summary

Run it:
```bash
python evaluation/benchmark.py            # uses test_questions.json, writes results/baseline.csv
```

---

## 2. The test set (112 verified pairs)

We have **112 verified question–SQL pairs**. Every gold SQL has been executed
against `gst_official` (all 112 run cleanly, no errors / empty / NULL results).

| Split | Counts |
|-------|--------|
| **By module** | EWB 42 · GSTR-3B 38 · GSTR-7 32 |
| **By difficulty** | simple 49 · moderate 35 · challenging 28 |
| **By category** | aggregation, filtering, grouping, ranking, join, subquery, having, decode, quirk, domain_specific |

**Difficulty tiers** (the standard Spider/BIRD framing):
- **simple** — one table, a basic `COUNT`/`SUM`/`AVG`/`WHERE`. *("How many e-way bills are there?")*
- **moderate** — a 2-table `JOIN`, `GROUP BY` + ranking, or a date/condition filter. *("Top 5 taxpayers by outward value in FY 2025-26")*
- **challenging** — 3+ tables, decode-table joins, subqueries, `HAVING`, or domain knowledge. *("Total state income per financial year, labelled by year" — needs the `fy_flag → mst_fy_years_t` decode join)*

The **category** tag is what we use to spot *repeating* failure patterns
(e.g. if `decode` joins fail systematically) — that's how we triage a real
weakness from a one-off, and decide general-fix vs RAG. The set deliberately
exercises the data quirks too: quoted identifiers (`"InvVal"`, `"range"`),
string-numeric casts (`travdist`), `VARCHAR` dates (`TO_DATE`), the partition
key (`fy_flag`), and the GSTR-7 FK-naming quirk.

---

## 3. The three metrics

### VER — Valid Execution Rate
**Question it answers:** *Does the generated SQL even run without a database error?*

- Computed as: fraction of predictions that execute successfully (after up to 3
  self-correction attempts).
- A failure here means broken SQL — a hallucinated column/table, a syntax error,
  a type mismatch, etc.
- VER ignores *correctness* — a query can run fine and still return the wrong
  answer. VER is a floor: "is the output even usable?"

### EX — Execution Accuracy  ★ primary metric
**Question it answers:** *Does the generated SQL return the same answer as gold?*

- Computed as: run both queries, compare the **result sets**.
- This is the metric that matters, and the one the thesis headlines.

**How we compare result sets (our exact definition):**
- Cell values are normalized: numbers rounded to 2 decimals, strings trimmed,
  `NULL` preserved (absorbs float noise and padding quirks).
- **Row order is ignored** by default (most questions aren't inherently ordered).
  For ranking questions ("top N"), the gold item is flagged `order_matters` and
  order is enforced.
- **Extra columns in the prediction are allowed.** The gold is written as the
  *minimal* answer; if the model also returns, say, a trade-name label column,
  it still counts as correct — as long as some selection of its columns
  reproduces gold's rows. Row-to-row correlation is preserved, so shuffling
  values across rows does **not** sneak through.

> Worked example. Q: "top 5 taxpayers by outward value."
> Gold rows: `(gstinA, 9.0M), (gstinB, 6.6M), …`
> Model returns `gstin, trade_name, value` — three columns. EX still passes,
> because the `(gstin, value)` projection matches gold exactly and in order.

### EM — Exact Match
**Question it answers:** *Is the SQL string essentially identical to gold?*

- Computed as: normalized string equality (lowercased, whitespace collapsed,
  trailing `;` removed).
- This is **strict and intentionally crude**. Two perfectly correct queries
  usually differ (alias names, column order, `COUNT(*)` vs `COUNT(col)`), so EM
  is almost always low. We report it only for completeness.
- **A low EM alongside a high EX is a good sign** — it means the model writes
  correct queries in its own style rather than parroting the reference.

---

## 4. What is a "good" score?

Scores only make sense relative to benchmarks. Two public ones anchor the field:

- **Spider** — cross-domain but *clean, small* schemas. Easier. Top systems reach
  **~89–91% EX**; "good" is **80%+**.
- **BIRD** — *large, dirty, real-world* databases needing domain knowledge.
  Much harder. SOTA is roughly **~65–73% EX**; strong single models land
  **~55–65%**; measured **human performance is ~92%**.

**Our setting is BIRD-like, not Spider-like:** real government schemas, dirty
data (VARCHAR dates, padded strings, reserved-word columns), 21+ tables, and
genuine GST domain knowledge. So **BIRD is the fair yardstick.**

Rough reading guide for our numbers:

| Metric | Weak | OK | Good | Notes |
|--------|------|----|----- |-------|
| **VER** | <85% | 85–92% | **95%+** | a healthy system rarely emits broken SQL |
| **EX**  | <50% | 50–65% | **65%+** (BIRD-like) | the headline; >80% is excellent for this domain |
| **EM**  | — | — | — | not a quality target; low-but-nonzero is normal |

Caveat on *our* current EX (~81%): it's **inflated by the small, simple-skewed
seed**. As we add the harder 100-item set (more challenging joins, decode tables,
domain traps), expect EX to settle toward the BIRD-like **60–75%** band. That
drop is expected and *correct* — it means the test set got more representative,
not that the model got worse.

The point of the baseline isn't the absolute number anyway — it's the
**reference line that RAG (Phase 5-B) must beat**. The thesis claim is
*"RAG improves EX over the static-prompt baseline on a domain-specific schema."*

---

## 5. Reading the output

`benchmark.py` prints a per-question line and a summary:

```
[ 7] ✓ EX=1 VER=1 EM=0 att=1 mode EWB | Which 3 HSN codes have the highest ...
...
OVERALL (n=21)   EX= 81.0%  VER= 90.5%  EM=  4.8%
by difficulty:  simple 90% · moderate 100% · challenging ~50%
by module:      EWB 80% · GSTR-3B 80% · GSTR-7 83%
```
- `✓` = correct (EX), `~` = ran but wrong answer, `✗` = failed to run.
- `att` = self-correction attempts used (1 = right first try).
- Per-question rows are saved to `results/baseline.csv` (gitignored, regenerable).

---

## 6. Methodology caveats (important)

1. **vLLM is usually — but not *guaranteed* — deterministic at temperature 0.**
   A 5-run baseline came back bitwise-stable (**EX 81.0% ± 0.0**), but we *did*
   observe a single question flip pass↔fail in earlier runs (likely tied to
   KV/prefix-cache state). So determinism isn't assured. Use `--runs N` to repeat
   and report **mean ± std** — it both gives the trustworthy number and *confirms*
   whether a run was stable (std = 0) or noisy (std > 0).
2. **EX is conservative on a small set.** With 21 items, ±1 question ≈ ±5 points.
   The 100+ set fixes this.
3. **Gold quality is load-bearing.** Every gold SQL is executed and eyeballed
   before being trusted; a wrong gold would silently mis-score the model.

---

## 7. Current baseline (seed, XiYanSQL-QwenCoder-7B, static prompt)

| Metric | Value (21-item seed, 5 runs) |
|--------|------------------------------|
| EX  | **81.0% ± 0.0** |
| VER | **90.5% ± 0.0** |
| EM  | ≈ 5% |

Per-difficulty (EX): simple 90% · moderate 100% · challenging 40%.
The same 4 questions failed on every run (#4, #9, #15, #21) — see the error
buckets below; these are the triage targets (general-fix vs RAG).

Stable real-error categories (the RAG/few-shot targets):
- **Name-traps** — "cancelled" → `canceldet` event log instead of `status='CNL'`; "deducted" → `amt_ded` (the base) instead of `iamt+camt+samt` (the tax).
- **Missed decode joins** — GSTR-3B financial-year label needs `fy_flag → common.mst_fy_years_t`; the model sometimes invents a column instead.
