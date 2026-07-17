# Results manifest — v2 (5-module normalized schema)

Index of every result file → config + headline numbers, so the dir stays trackable.
EX = Execution Accuracy, VER = Valid Execution Rate, over the **172-question** v2 gold
set (`evaluation/test_questions.json`). Few-shot pool = `evaluation/rag_qsql_store.json`
(185). Held-out run-once = `evaluation/heldout_questions.json` (42).

> The v1 3-module (flat-MV GSTR-3B) results — baseline 90.2% / Full RAG 98.2% on the
> 112-question set, all CSVs + the v1 manifest — are archived under
> `archive_v1_3module/`. They are provenance, **not** the v2 headline.

## Current (v2) — data audits done, XiYan runs done, Qwen runs pending (5xx-blocked)

| file | what | status |
|---|---|---|
| `distinguishability_audit.csv` | plausible-wrong collision audit (seed=42) on the 172 gold | **21/171 (12.3%) collide, ALL domain-invariant, 0 seed-fixable** — the documented residual bound |
| `leakage_audit.csv` | pool↔gold + held-out↔(gold+pool) disjointness | **0 SQL template-twins (PASS)** |
| `intrinsic_bge-large-en-v1.5_{semantic,hybrid}.csv` | Layer-1 few-shot retrieval recall (v2 185-pool, k=5) | **hybrid** same-both@5 **87.8%** (MRR 0.708) > semantic 84.3% (0.675) — hybrid kept |
| `intrinsic_schema_k{3,5}_core{on,off}.csv` | Layer-1 SCHEMA retrieval recall (v2 39-table schema) | **k5+core-on** best: table-recall **86.4%**, full-cover **71.5%**, decode 54.5%, mean 7.0 tab (GSTR-3B full-cover is the weak spot — normalized 3B spans many leaf tables) |

## Phase 8 step 6 — v2 model runs (EX% / VER%, runs=3)

4 configs × 2 models on the 172 gold set. XiYan (local vLLM) **all done**; Qwen
(hosted lab API) **partly blocked on a Cloudflare 502** from the co-tenant origin.

### Gold (172)

| config | XiYanSQL-7B | Qwen-27B |
|---|---|---|
| Baseline (static full schema) | 73.8 / 92.4 | 87.8 / 100 |
| Schema-only RAG (retrieved k5 + core) | 71.5 / 93.0 | 82.0 / 97.1 |
| Few-shot RAG (hybrid k5) | **90.3 / 97.9** | *pending — re-run* † |
| Full RAG (schema + few-shot) | 87.4 / 98.8 | *pending (502)* |

### Held-out (42, run-once)

| config | XiYanSQL-7B | Qwen-27B |
|---|---|---|
| Baseline | 69.0 / 85.7 | *pending (502)* |
| Schema-only RAG | 66.7 / 81.0 | *pending (502)* |
| Few-shot RAG | **92.9 / 95.2** | *pending (502)* |
| Full RAG | 85.7 / 92.9 | *pending (502)* |

**XiYan v2 headline:** few-shot (90.3) **>** full RAG (87.4); schema-only (71.5) < baseline
(73.8) → retrieved schema *hurts* the 7B, even combined. Opposite of v1 (full RAG was top).
Held-out confirms the ordering (few-shot 92.9 leads).

† **Qwen few-shot re-run reason:** the first run (EX 84.3, preserved as
`qwen27b_rag_fewshot_overflow1500.csv`) was contaminated by a 32K-window overflow — at
`qwen_max_tokens=1500` the static schema (30.5K Qwen tok) + retrieved GSTR-3B demos exceeded
32768 → server 400 → 21 empty-SQL fails (all GSTR-3B, the longest demos). Fixed by
`qwen_max_tokens=500` (thinking-OFF output ≤238 tok, so no truncation; frees ~1000 tok of
demo room). Re-run queued in `qwen_rerun.sh`. This overflow is itself a v2 finding — the
normalized-schema static prompt leaves a 27B model no room for few-shots, extra RAG motivation.

**Still pending (gated on Qwen origin):** gold few-shot re-run + gold full-RAG + all 4
held-out Qwen runs (6 total). Then: v2 2×2 tables, `stats.py` (McNemar + Wilson CIs) on v2.

**Model roles:** XiYanSQL-7B = primary deployable (≤10B cap); Qwen-27B = upper-bound
comparison only (27B > cap, hosted lab API — nothing ships on it).
</content>
