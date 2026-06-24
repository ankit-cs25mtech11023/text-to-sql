"""Leakage audit (RAG_plan §2): the few-shot pool must be DISJOINT from the eval set.

Embeds every pool question and every eval question with the retrieval embedding model,
then flags any pool->eval pair with cosine similarity above THRESHOLD for manual review.
A high-similarity pair means the retriever could hand the model a near-paraphrase of a
test question (and its gold SQL), inflating RAG numbers in a way that does not generalize.

Two leak signals are reported:
  1. question cosine > THRESHOLD (semantic near-paraphrase). On this short, single-domain
     question set bge-large compresses same-TEMPLATE questions high (~0.90-0.97) even when the
     gold SQL differs, so cosine alone over-counts: it flags intended same-pattern coverage.
  2. SQL TEMPLATE-TWIN: gold SQL identical after masking literals (numbers/strings). This is the
     real leak test — a twin means the model could copy the answer by swapping one constant.
     The pool is authored so that (2) is ZERO; (1) is reported for transparency.

Run: python evaluation/leakage_audit.py [--model BAAI/bge-large-en-v1.5] [--threshold 0.90]
Writes evaluation/results/leakage_audit.csv (every pool item + its closest eval match).
"""

from __future__ import annotations

import argparse
import csv
import json
import pathlib
import re

import numpy as np
from sentence_transformers import SentenceTransformer


def mask_literals(sql: str) -> str:
    """Normalize SQL and replace string/numeric literals with '?' so two queries that differ
    ONLY in a constant (e.g. fp='102025' vs '112025', igstrt=18 vs 28) compare equal."""
    s = re.sub(r"\s+", " ", sql.strip().lower())
    s = re.sub(r"'[^']*'", "'?'", s)
    s = re.sub(r"\b\d+\b", "?", s)
    return s

ROOT = pathlib.Path(__file__).resolve().parent
POOL = ROOT / "rag_qsql_store.json"
EVAL = ROOT / "test_questions.json"
OUT = ROOT / "results" / "leakage_audit.csv"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="BAAI/bge-large-en-v1.5")
    ap.add_argument("--threshold", type=float, default=0.90)
    args = ap.parse_args()

    pool = json.loads(POOL.read_text())
    eval_set = json.loads(EVAL.read_text())
    pool_q = [p["question"] for p in pool]
    eval_q = [e["question"] for e in eval_set]

    model = SentenceTransformer(args.model)
    # normalized embeddings -> dot product is cosine similarity; deterministic encode
    pe = model.encode(pool_q, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    ee = model.encode(eval_q, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False)
    sim = pe @ ee.T  # (n_pool, n_eval)

    best_idx = sim.argmax(axis=1)
    best_sim = sim.max(axis=1)

    eval_masked = [mask_literals(e["gold_sql"]) for e in eval_set]

    OUT.parent.mkdir(parents=True, exist_ok=True)
    flagged = []
    twins = []
    with OUT.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["pool_id", "pool_category", "max_cosine", "closest_eval_id", "flagged_cosine",
                    "sql_template_twin", "pool_question", "closest_eval_question"])
        for i, p in enumerate(pool):
            j = int(best_idx[i])
            cos = float(best_sim[i])
            flag = cos > args.threshold
            # a twin = gold SQL identical-after-literal-masking to ANY eval item
            pmask = mask_literals(p["gold_sql"])
            twin_eid = next((eval_set[k]["id"] for k, em in enumerate(eval_masked) if em == pmask), None)
            if flag:
                flagged.append((p["id"], eval_set[j]["id"], round(cos, 4)))
            if twin_eid is not None:
                twins.append((p["id"], twin_eid, round(cos, 4)))
            w.writerow([p["id"], p["category"], round(cos, 4), eval_set[j]["id"], int(flag),
                        "" if twin_eid is None else twin_eid, p["question"], eval_set[j]["question"]])

    print(f"model={args.model}  threshold={args.threshold}")
    print(f"pool={len(pool)}  eval={len(eval_set)}")
    print(f"max cosine over all pool items = {best_sim.max():.4f} (pool #{pool[int(best_sim.argmax())]['id']})")
    print(f"mean closest-cosine = {best_sim.mean():.4f}")
    print(f"signal 1 — cosine > {args.threshold} (template similarity, expected): {len(flagged)}")
    print(f"signal 2 — SQL TEMPLATE-TWINS (real leak test): {len(twins)}")
    for pid, eid, cos in sorted(twins, key=lambda x: -x[2]):
        print(f"  TWIN pool #{pid}  ~  eval #{eid}   cosine={cos}")
    if not twins:
        print("  none — no pool gold SQL is recoverable from an eval item by swapping a literal. PASS.")
    print(f"report -> {OUT}")


if __name__ == "__main__":
    main()
