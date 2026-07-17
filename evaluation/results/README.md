# Results manifest — v2 (5-module normalized schema)

Index of every result file → config + headline numbers, so the dir stays trackable.
EX = Execution Accuracy, VER = Valid Execution Rate, over the **172-question** v2 gold
set (`evaluation/test_questions.json`). Few-shot pool = `evaluation/rag_qsql_store.json`
(185). Held-out run-once = `evaluation/heldout_questions.json` (42).

> The v1 3-module (flat-MV GSTR-3B) results — baseline 90.2% / Full RAG 98.2% on the
> 112-question set, all CSVs + the v1 manifest — are archived under
> `archive_v1_3module/`. They are provenance, **not** the v2 headline.

## Current (v2) — data audits done, model runs pending

| file | what | status |
|---|---|---|
| `distinguishability_audit.csv` | plausible-wrong collision audit (seed=42) on the 172 gold | **21/171 (12.3%) collide, ALL domain-invariant, 0 seed-fixable** — the documented residual bound |
| `leakage_audit.csv` | pool↔gold + held-out↔(gold+pool) disjointness | **0 SQL template-twins (PASS)** |
| `intrinsic_bge-large-en-v1.5_{semantic,hybrid}.csv` | Layer-1 few-shot retrieval recall (v2 185-pool, k=5) | **hybrid** same-both@5 **87.8%** (MRR 0.708) > semantic 84.3% (0.675) — hybrid kept |
| `intrinsic_schema_k{3,5}_core{on,off}.csv` | Layer-1 SCHEMA retrieval recall (v2 39-table schema) | **k5+core-on** best: table-recall **86.4%**, full-cover **71.5%**, decode 54.5%, mean 7.0 tab (GSTR-3B full-cover is the weak spot — normalized 3B spans many leaf tables) |

## Pending — Phase 8 step 6 (v2 full runs, gated on HPC vLLM tunnel)

4 configs × 2 models × runs=3 on the 172 gold set + held-out 42 run-once:

| config | XiYanSQL-7B | Qwen-27B |
|---|---|---|
| Baseline (static full schema) | — | — |
| Schema-only RAG (retrieved k5 + core) | — | — |
| Few-shot RAG (hybrid k5) | — | — |
| Full RAG (schema + few-shot) | — | — |

Then: v2 2×2 tables, `stats.py` (McNemar + Wilson CIs) on v2, held-out report.

**Model roles:** XiYanSQL-7B = primary deployable (≤10B cap); Qwen-27B = upper-bound
comparison only (27B > cap, hosted lab API — nothing ships on it).
</content>
