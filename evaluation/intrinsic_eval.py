"""Layer-1 intrinsic retrieval eval (RAG_plan §3.5) — CPU only, no LLM, no tunnel.

Scores the few-shot retriever against the 172 eval questions using their gold
category/module as the relevance label (offline IR ground-truth — NOT a deployment
signal; the runtime category rerank predicts from text). For each eval question it
retrieves top-k pool few-shots and measures whether a same-pattern demo was fetched.

Metrics per config:
- same-category hit@k   — any retrieved pool item shares the eval question's category
- same-module  hit@k    — ... shares its module
- same-both    hit@k    — shares BOTH (the strict "right pattern in the right module")
- MRR_cat               — 1/rank of the first same-category hit (0 if none in top-k)
- retrieval latency     — mean ms/query

Selecting the winning retriever config here avoids a combinatorial blowup of
end-to-end EX runs through the HPC tunnel. Writes one CSV per config + a summary.

Run (default sweep = bge-large x {semantic,hybrid}; add bge-m3 to download+compare):
    python evaluation/intrinsic_eval.py
    python evaluation/intrinsic_eval.py --embed-models BAAI/bge-large-en-v1.5 BAAI/bge-m3
    python evaluation/intrinsic_eval.py --modes semantic hybrid --k 3
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from core.rag_retriever import RAGRetriever

EVAL = Path(__file__).resolve().parent / "test_questions.json"
RESULTS = Path(__file__).resolve().parent / "results"


def _cfg_tag(embed_model: str, mode: str, cat_w: float) -> str:
    em = embed_model.split("/")[-1]
    tag = f"{em}_{mode}"
    if cat_w > 0:
        tag += f"_cat{cat_w}"
    return tag


def _eval_one_config(eval_items, embed_model, mode, cat_w, k):
    settings = get_settings()
    settings.embed_model = embed_model
    settings.rag_retrieval_mode = mode
    settings.rag_category_weight = cat_w
    settings.rag_top_k_fewshots = k

    retriever = RAGRetriever(settings)

    rows = []
    for it in eval_items:
        t0 = time.perf_counter()
        shots = retriever.retrieve_fewshots(it["question"], k)
        latency_ms = (time.perf_counter() - t0) * 1000.0

        cats = [s["category"] for s in shots]
        mods = [s["module"] for s in shots]
        cat_hit = int(it["category"] in cats)
        mod_hit = int(it["module"] in mods)
        both_hit = int(any(s["category"] == it["category"] and s["module"] == it["module"] for s in shots))
        first_cat_rank = next((r + 1 for r, c in enumerate(cats) if c == it["category"]), 0)
        rows.append({
            "id": it["id"], "category": it["category"], "module": it["module"],
            "cat_hit": cat_hit, "mod_hit": mod_hit, "both_hit": both_hit,
            "mrr_cat": round(1.0 / first_cat_rank, 4) if first_cat_rank else 0.0,
            "first_cat_rank": first_cat_rank,
            "retrieved_ids": "|".join(str(s["id"]) for s in shots),
            "retrieved_cats": "|".join(cats),
            "latency_ms": round(latency_ms, 2),
        })
    return rows


def _summary(tag, rows, k):
    n = len(rows)
    cat = 100 * sum(r["cat_hit"] for r in rows) / n
    mod = 100 * sum(r["mod_hit"] for r in rows) / n
    both = 100 * sum(r["both_hit"] for r in rows) / n
    mrr = sum(r["mrr_cat"] for r in rows) / n
    lat = sum(r["latency_ms"] for r in rows) / n
    print(f"\n[{tag}]  k={k}  n={n}")
    print(f"  same-category hit@k = {cat:5.1f}%   same-module hit@k = {mod:5.1f}%   same-both hit@k = {both:5.1f}%")
    print(f"  MRR(category) = {mrr:.3f}   mean latency = {lat:.1f} ms/query")

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_cat[r["category"]].append(r)
    print("  by category (same-both hit@k):")
    for c, grp in sorted(by_cat.items()):
        h = 100 * sum(r["both_hit"] for r in grp) / len(grp)
        print(f"    {c:16} n={len(grp):2}  {h:5.1f}%")
    return {"tag": tag, "cat_hit": cat, "mod_hit": mod, "both_hit": both, "mrr": mrr, "latency_ms": lat}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(EVAL))
    ap.add_argument("--embed-models", nargs="+", default=["BAAI/bge-large-en-v1.5"])
    ap.add_argument("--modes", nargs="+", default=["semantic", "hybrid"])
    ap.add_argument("--category-weights", nargs="+", type=float, default=[0.0])
    ap.add_argument("--k", type=int, default=3)
    args = ap.parse_args()

    eval_items = json.loads(Path(args.eval).read_text())
    RESULTS.mkdir(parents=True, exist_ok=True)

    summaries = []
    for embed_model in args.embed_models:
        for mode in args.modes:
            for cat_w in args.category_weights:
                tag = _cfg_tag(embed_model, mode, cat_w)
                rows = _eval_one_config(eval_items, embed_model, mode, cat_w, args.k)
                out = RESULTS / f"intrinsic_{tag}.csv"
                with out.open("w", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                    w.writeheader()
                    w.writerows(rows)
                summaries.append(_summary(tag, rows, args.k))
                print(f"  -> {out}")

    print("\n" + "=" * 78)
    print(f"{'config':40} {'cat@k':>7} {'mod@k':>7} {'both@k':>7} {'MRR':>6}")
    for s in sorted(summaries, key=lambda x: -x["both_hit"]):
        print(f"{s['tag']:40} {s['cat_hit']:6.1f}% {s['mod_hit']:6.1f}% {s['both_hit']:6.1f}% {s['mrr']:6.3f}")
    print("Winner = highest same-both hit@k (tie-break MRR, then lower latency).")


if __name__ == "__main__":
    main()
