# Results manifest (local, gitignored)

Index of every result file → config + headline numbers, so the dir stays trackable.
EX = Execution Accuracy, VER = Valid Execution Rate, over the 112-question frozen eval set
(`evaluation/test_questions.json`). Few-shot pool = `evaluation/rag_qsql_store.json`.

## Active / canonical (root — scripts write here, docs reference these names)

hard-fail = ids that failed EX on **every** run (0/N); flaky = passed some-not-all (none here).

| file | config | EX | VER | runs | hard-fail (0/N EX) | note |
|---|---|---|---|---|---|---|
| `baseline.csv` | static full schema, no RAG | 90.2% | 97.6% | 3 | {35,48,71,72,74,78,97,99,102,104} | Grid-A baseline (post-triage) |
| `baseline_pretriage_runs1_snapshot.csv` | static, pre-triage | 86.6% | — | 1 | {4,33,35,48,62,68,71,72,74,77,78,79,97,99,102} | historical, before general fixes |
| `rag_fewshot.csv` | **few-shot RAG, hybrid k=5, 142-pool** | **97.3% ±0.0** | **100% ±0.0** | 3 | **{62,96,107}** | few-shot-only Grid-A cell (= ablations/rag_fewshot_hyb_k5_r3.csv) |
| `rag_schema.csv` | schema-only RAG, retrieved k5 + always-core | 86.6% ±0.0 | 97.3% ±0.0 | 3 | {4,48,62,65,67,71,74,78,88,94,97,99,102,107,108} | schema-only Grid-A cell — **BELOW baseline** (retrieval drops needed tables; decode stuck 25%); ~8.6k tok |
| `rag.csv` | **full RAG, retrieved k5 + always-core, hybrid k5 few-shot** | **98.2% ±0.0** | **100% ±0.0** | 3 | **{62,107}** | **HEADLINE** — best EX + ~8.8k tok (vs ~20.1k baseline); decode 25%→100% |
| `rag_traces.jsonl` | per-question retrieval traces | — | — | — | — | **headline (full-RAG core-on) run-1 traces** (restored after core-off ablation) |
| `leakage_audit.csv` | pool↔eval disjointness | — | — | — | — | **0 SQL template-twins (PASS)**; 62 benign cosine-flags |
| `intrinsic_bge-large-en-v1.5_{semantic,hybrid}.csv` | Layer-1 few-shot retrieval recall | — | — | — | — | hybrid > semantic (both@k 91.1 vs 86.6 @k5) |
| `intrinsic_bge-m3_{semantic,hybrid}.csv` | Layer-1, bge-m3 challenger | — | — | — | — | ~tie with bge-large; bge-large kept |
| `intrinsic_schema_k{3,5}_core{on,off}.csv` | **Layer-1 SCHEMA retrieval recall** (gold-table coverage) | — | — | — | — | k5+core-on best: table-recall 98.2%, full-cover 96.4%, **decode-cover 20%**, mean 6.7 tab |

## ablations/ (frozen evidence — never auto-rewritten)

Grid-B = few-shot retriever sweep (mode × k) on the 142-pool:

| file | config | EX | VER | runs | hard-fail (0/N EX) | note |
|---|---|---|---|---|---|---|
| `rag_fewshot_pool140_sem_k3.csv` | sem k=3, **old 140-pool** | 94.6% | 100% | 3 | {59,62,94,96,107,109} | prior few-shot headline (before pool fix #1141/#1142) |
| `rag_fewshot_sem_k3.csv` | sem k=3, 142-pool | 95.5% | 100% | 1 | {59,62,94,96,107} | pool fix isolated → fixed #109 |
| `rag_fewshot_hyb_k3.csv` | hyb k=3 | 96.4% | 99.1% | 1 | {28,59,62,107} | +mode but broke #28 + 1 invalid SQL |
| `rag_fewshot_sem_k5.csv` | sem k=5 | 97.3% | 100% | 1 | {62,96,107} | +k fixed #59,#94 |
| `rag_fewshot_hyb_k5.csv` | hyb k=5 | 97.3% | 100% | 1 | {62,96,107} | ties sem at k5 |
| `rag_fewshot_sem_k5_r3.csv` | sem k=5 | 97.3% ±0.0 | 100% | 3 | {62,96,107} | confirm |
| `rag_fewshot_hyb_k5_r3.csv` | **hyb k=5** | **97.3% ±0.0** | **100%** | 3 | **{62,96,107}** | confirm = winner; promoted to rag_fewshot.csv |

**Winner pick:** sem-k5 and hyb-k5 are bitwise identical on eval → hybrid chosen on
eval-*independent* grounds (intrinsic recall + lexical robustness for unseen jargon).

**Residuals at few-shot winner {62, 96, 107}** = documented findings: #96 base-vs-withheld
phrasing collision (per-deductee) — **fixed by full RAG** (retrieved schema removes 21-table
distraction); #107 grouping-entity + 3-table (still fails at full RAG); #62 decode-label-vs-raw
(baseline-flaky).

### Always-core ablation (#6) — full-RAG, core toggled

| file | config | EX | VER | runs | hard-fail | note |
|---|---|---|---|---|---|---|
| `rag_both_coreoff.csv` | full RAG, always-core **OFF** | 98.2% ±0.0 | 100% | 3 | {62,107} | **EX-neutral** vs core-on (98.2%, same fails) but **~6.1k tok** (vs ~8.8k). Few-shots compensate for dropped MAIN tables → core net is EX-redundant here, kept ON as robust default. |

Trace backups (one per cell, kept since `rag_traces.jsonl` is a fixed path overwritten each run):
`rag_traces_fewshot.jsonl`, `rag_traces_schema.jsonl`, `rag_traces_both.jsonl` (= headline core-on),
`rag_traces_both_coreoff.jsonl`.

## Grid-A complete (2×2)

| Configuration | Schema | Few-shot | EX | VER | ~tokens |
|---|---|---|---|---|---|
| Baseline | full static | no | 90.2% | 97.6% | ~20.1k |
| Schema-only | retrieved k5+core | no | 86.6% | 97.3% | ~8.6k |
| Few-shot only | full static | hybrid k5 | 97.3% | 100% | ~20.2k |
| **Full RAG (headline)** | retrieved k5+core | hybrid k5 | **98.2%** | **100%** | **~8.8k** |

Schema-retrieval alone *hurts* (drops needed tables); few-shot is the workhorse (+7.1);
retrieved schema pays off only *with* few-shots (+0.9, fixes #96) while cutting tokens ~57%.
