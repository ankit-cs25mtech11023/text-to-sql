# Results manifest — v2 (5-module normalized schema)

Index of every result file → config + headline numbers, so the dir stays trackable.
EX = Execution Accuracy, VER = Valid Execution Rate, over the **172-question** v2 gold
set (`evaluation/test_questions.json`). Few-shot pool = `evaluation/rag_qsql_store.json`
(185). Held-out run-once = `evaluation/heldout_questions.json` (42).

> The v1 3-module (flat-MV GSTR-3B) results — baseline 90.2% / Full RAG 98.2% on the
> 112-question set, all CSVs + the v1 manifest — are archived under
> `archive_v1_3module/`. They are provenance, **not** the v2 headline.

## Data audits (v2)

| file | what | status |
|---|---|---|
| `distinguishability_audit.csv` | plausible-wrong collision audit (seed=42) on the 172 gold | **21/171 (12.3%) collide, ALL domain-invariant, 0 seed-fixable** — the documented residual bound |
| `leakage_audit.csv` | pool↔gold + held-out↔(gold+pool) disjointness | **0 SQL template-twins (PASS)** |
| `intrinsic_bge-large-en-v1.5_{semantic,hybrid}.csv` | Layer-1 few-shot retrieval recall (v2 185-pool, k=5) | **hybrid** same-both@5 **87.8%** (MRR 0.708) > semantic 84.3% (0.675) — hybrid kept |
| `intrinsic_schema_k{3,5,6,7}_core{on,off}.csv` | Layer-1 SCHEMA retrieval recall (v2 39-table schema, post-fix blocks) | **k6+core-on locked**: table-recall **99.1%**, full-cover **98.3%**, decode **100%** (pre-fix k5: 86.4/71.5/54.5). k5=97.7, k7=98.8 (only adds #79) — k chosen on intrinsic, not eval EX |

## Schema-retrieval fix (commit `e3f48b9`, 2026-07-18)

First-pass v2 runs showed full-RAG **below** few-shot for the 7B (87.4 vs 90.3) — root-caused
from traces into two failure classes, then fixed structurally (no eval tuning):

- **Coverage class:** `common.*` masters + FK-bridge parents (sup_details, inward_sup,
  itc_elg, tx_pmt) semantically bland → never retrieved; identical-column section siblings
  crowd the k slots. → Fix: 4 masters added to `_CORE_TABLES`; **FK-ancestor closure** in
  `SchemaIndexer` (any retrieved table pulls its FK parents); k 5→6.
- **Grounding class (7B-specific):** M-Schema blocks lacked data values; XiYanSQL's trained
  M-Schema format includes per-column `Examples: [...]`. → Fix: live-DB examples per column
  in `get_table_blocks` (also makes retrieval value-aware).

Post-fix coverage audit across ALL RAG-config fails, both models: **only #131 (+#79
XiYan-schema) still miss a gold table** — coverage essentially solved; residual failures are
model-behavior classes (below). Stale pre-fix numbers (XiYan schema 71.5 / full 87.4, Qwen
schema 82.0, held-out schema 66.7 / full 85.7) are superseded and not citable.

## Phase 8 step 6 — v2 model runs (EX% / VER%, runs=3, post-fix)

### Gold (172)

| config | XiYanSQL-7B | Qwen-27B |
|---|---|---|
| Baseline (static full schema, ~21K tok) | 73.8 / 92.4 | 87.8 / 100 |
| Schema-only RAG (retrieved k6 + core) | 73.4 ±0.3 / 92.4 | 88.4 / 98.8 |
| Few-shot RAG (hybrid k5) | 90.3 / 97.9 | **98.3 / 100** |
| Full RAG (schema + few-shot, ~10K tok) | **90.7 ±0.0 / 97.9** | 96.5 / 100 |

### Held-out (42, run-once)

| config | XiYanSQL-7B | Qwen-27B |
|---|---|---|
| Baseline | 69.0 / 85.7 | 85.7 / 100 |
| Schema-only RAG | 76.2 / 85.7 | 92.9 / 97.6 |
| Few-shot RAG | 92.9 / 95.2 | 100 / 100 |
| Full RAG | **92.9 / 97.6** | **100 / 100** |

**v2 headline (XiYan-7B, the deployable):** full RAG **90.7** ≥ few-shot 90.3 ≫ baseline
73.8; schema-only 73.4 ≈ baseline (the v1 "schema-retrieval hurts" interference is gone
post-fix). Held-out confirms (92.9 both RAG configs vs 69.0 baseline). Full RAG does it at
~10K tok vs ~21K static.

**Qwen-27B (upper bound):** few-shot 98.3 > full RAG 96.5 — gap = 3 questions, McNemar
p=0.25, **not significant**; mechanism taxonomy below. Full RAG is still the config that
*fits*: the 30.5K-token static prompt forced `qwen_max_tokens=500` against the 32K window
(the few-shot config's first run overflowed — preserved as
`qwen27b_rag_fewshot_overflow1500.csv`); full RAG runs at ~12K with ample room.

## Stats (`stats_wilson_ci.csv`, `stats_mcnemar.csv`, majority-binarized EX)

- **RAG gain significant, both models:** XiYan baseline→full-RAG +34/−5 flips, p<0.0001;
  Qwen +20/−5, p=0.0041.
- **Few-shot vs full-RAG NOT significant, both models:** XiYan +3/−2 p=1.0; Qwen 0/+3 p=0.25.
  Schema retrieval on top of few-shots = token savings + coverage insurance, not EX movement.
- **Schema-only vs baseline NOT significant, both models** (XiYan p=1.0, Qwen p=1.0) —
  v1's interference finding neutralized by the fix.
- **Model gap significant:** Qwen > XiYan baseline p=0.0007; full-RAG p=0.0213. RAG shrinks
  the 7B↔27B gap from 14.0 to 5.8 EX points.

## Qwen full-RAG < few-shot: failure taxonomy (all fails classified from traces)

Qwen full-RAG fails {60, 66, 71, 124, 131, 143}; schema-only adds {45, 69, 76, 134}.
Every fail's retrieved set was audited against its gold tables:

| class | ids | mechanism |
|---|---|---|
| **A. Mirror distraction** | 60 (full); 45, 69, 76 (schema-cfg) | "tax paid/payable" retrieves BOTH the 3B payment subtree and its GSTR-7 mirror (`tax_paid*`, `tax_pay`); prompt caption "RELEVANT TABLES (retrieved for this question)" endorses the distractors → module flip (#60, #76) or column-bleed `sgst_tx` onto 3B pd_cash (#45, #69 — persisted through 3 self-correction rounds). Same model + neutral full schema routes correctly 3/3 → presentation bias, not knowledge gap |
| **B. Coverage** | 131 (+79 XiYan-schema) | the ONLY true retrieval miss post-fix: `tx_pmt` subtree crowded out despite exact lexical cues ("cash", "ITC", "payment") — a BM25-shaped hole in semantic-only schema retrieval |
| **C. Demo-pattern override** | 66, 124 (fail few-shot config too — not the gap) | #66: retrieved demos' bare-count template overrides the descriptions-taught `txval>0` "reported" guard (baseline passes). #124: demos teach entity=gstin projection; gold expects `trdnm` — arguably gold-side (GSTIN is the canonical unique taxpayer id; names non-unique) |
| **D. One-offs** | 71, 134 (schema-cfg) | `ipd` summed for "CGST paid" (cpd described one line below); `LIMIT 100` instead of `LIMIT 1` on an argmin. Deterministic but idiosyncratic |
| **E. Gold type-strictness** | 143 (all 4 configs) | quirk category demands `TO_DATE(fil_dt)`; generalist returns raw VARCHAR date. Not RAG-related — specialist-vs-generalist convention finding |

## Parked fixes (post-presentation; any change re-runs the RAG matrix ~2.5h)

| target | fix | rationale guard |
|---|---|---|
| Class A | reword RAG caption → "CANDIDATE TABLES (automatically retrieved; may include irrelevant tables — route per the module map)" | corrects a false assertion; general, not eval-shaped |
| Class B | schema-side hybrid BM25+RRF | parity with few-shot side (hybrid won on intrinsic, v1 AND v2); select on intrinsic full-cover only |
| Class C #124 | id-vs-name entity-projection convention audit across ALL golds, applied uniformly | data-quality pass, precedent = v1 entity-only triage |
| Class C #66 | 1–2 GENERAL pool demos: "reported X" = value>0 vs row-exists, on a different table than isuprev | v1 pool-fix precedent; must re-pass leakage audit |
| Class D, E | no code/data change — documented residuals | — |

## Model roles

XiYanSQL-7B = primary deployable (≤10B cap); Qwen-27B = upper-bound comparison only
(27B > cap, hosted lab API — nothing ships on it).
