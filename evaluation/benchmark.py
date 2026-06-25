"""Batch evaluation runner.

Runs every gold question through the pipeline, compares the predicted result to
the gold result, and writes per-question scores + a summary.

vLLM is not bitwise-deterministic even at temperature 0, so a single run has
~±5% noise on a small set. Use --runs N to repeat and report mean ± std (the
trustworthy number) plus per-question pass-rates.

Usage:
    python evaluation/benchmark.py
    python evaluation/benchmark.py --runs 3
    python evaluation/benchmark.py --test evaluation/test_questions.json \
                                   --output evaluation/results/baseline.csv --runs 5
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from core.pipeline import TextToSQLPipeline
from core.sql_executor import execute_sql
from database.connection import get_engine
from evaluation.metrics import exact_match, execution_match

FIELDS = [
    "id", "module", "difficulty", "category", "question", "gold_sql", "runs",
    "ex_passes", "ver_passes", "em_passes", "ex_rate", "ver_rate",
    "last_pred_sql", "last_error",
]


def _score_once(pipeline, gold_engine, items, limit, trace_rows=None) -> dict[int, dict]:
    """One full pass over the gold set -> {id: {ex, ver, em, pred_sql, error}}.

    If trace_rows is a list (RAG run, first pass only), append one retrieval trace
    per question for the Error Analysis chapter (RAG_plan #10) + efficiency (#9).
    """
    out: dict[int, dict] = {}
    for it in tqdm(items, desc="scoring", unit="q", leave=False):
        res = pipeline.ask(it["question"])
        gold = execute_sql(it["gold_sql"], gold_engine, limit=limit)
        ver = res.success
        ex = (
            execution_match(gold.data, res.data, order_matters=it.get("order_matters", False))
            if ver and gold.success else False
        )
        out[it["id"]] = {
            "ex": int(ex), "ver": int(ver), "em": int(exact_match(it["gold_sql"], res.sql)),
            "pred_sql": res.sql, "error": (res.error or "") if not ver else "",
        }
        if trace_rows is not None:
            _append_trace(trace_rows, pipeline, it, res, ex, ver)
    return out


def _append_trace(trace_rows, pipeline, it, res, ex, ver) -> None:
    import time

    from core.rag_retriever import _predict_category

    t0 = time.perf_counter()
    retr = pipeline._retriever.retrieve(it["question"])
    retrieval_ms = (time.perf_counter() - t0) * 1000.0
    msgs = pipeline._generator._prompt_builder.build_messages(it["question"])
    prompt_chars = sum(len(m["content"]) for m in msgs)
    trace_rows.append({
        "id": it["id"], "module": it["module"], "category": it["category"],
        "question": it["question"],
        "predicted_category": _predict_category(it["question"]),
        "retrieved_tables": retr["tables"],
        "retrieved_fewshot_ids": [s["id"] for s in retr["fewshots"]],
        "generated_sql": res.sql, "gold_sql": it["gold_sql"],
        "exec_rowcount": int(res.data.shape[0]) if (ver and res.data is not None) else 0,
        "ex": int(ex), "ver": int(ver), "attempts": res.attempts,
        "retrieval_latency_ms": round(retrieval_ms, 2),
        "prompt_chars": prompt_chars, "approx_prompt_tokens": prompt_chars // 4,
        "execution_time_ms": round(res.execution_time_ms, 2),
    })


def run(test_path: str, out_path: str, runs: int, rag: bool = False, rag_mode: str = "both",
        retrieval_mode: str | None = None, rag_top_k: int | None = None) -> None:
    settings = get_settings()
    if rag:
        overrides: dict = {}
        if retrieval_mode is not None:
            overrides["rag_retrieval_mode"] = retrieval_mode
        if rag_top_k is not None:
            overrides["rag_top_k_fewshots"] = rag_top_k
        if overrides:
            settings = settings.model_copy(update=overrides)
        from core.rag_pipeline import RAGTextToSQLPipeline  # lazy: keeps baseline startup light
        pipeline = RAGTextToSQLPipeline(settings, rag_mode=rag_mode)
        print(f"RAG pipeline: mode={rag_mode}  embed={settings.embed_model}  "
              f"retrieval={settings.rag_retrieval_mode}  k_fewshots={settings.rag_top_k_fewshots}")
    else:
        pipeline = TextToSQLPipeline(settings)
    gold_engine = get_engine(
        settings.database_url, read_only=True,
        statement_timeout_seconds=settings.query_timeout_seconds,
    )
    items = json.loads(Path(test_path).read_text())

    passes: dict[int, dict[str, int]] = {it["id"]: {"ex": 0, "ver": 0, "em": 0} for it in items}
    last: dict[int, dict] = {}
    per_run_overall: list[dict[str, float]] = []  # overall EX/VER per run, for mean +/- std
    trace_rows: list[dict] | None = [] if rag else None

    for r in range(1, runs + 1):
        collect = trace_rows if (rag and r == 1) else None  # traces once, run 1
        scored = _score_once(pipeline, gold_engine, items, settings.query_result_limit, collect)
        for qid, s in scored.items():
            passes[qid]["ex"] += s["ex"]
            passes[qid]["ver"] += s["ver"]
            passes[qid]["em"] += s["em"]
            last[qid] = s
        n = len(items)
        per_run_overall.append({
            "ex": sum(s["ex"] for s in scored.values()) / n,
            "ver": sum(s["ver"] for s in scored.values()) / n,
        })
        if runs > 1:
            o = per_run_overall[-1]
            print(f"  run {r}/{runs}: EX={100*o['ex']:5.1f}%  VER={100*o['ver']:5.1f}%")

    rows = []
    for it in items:
        p = passes[it["id"]]
        rows.append({
            "id": it["id"], "module": it["module"], "difficulty": it["difficulty"],
            "category": it["category"], "question": it["question"], "gold_sql": it["gold_sql"],
            "runs": runs, "ex_passes": p["ex"], "ver_passes": p["ver"], "em_passes": p["em"],
            "ex_rate": round(p["ex"] / runs, 3), "ver_rate": round(p["ver"] / runs, 3),
            "last_pred_sql": last[it["id"]]["pred_sql"], "last_error": last[it["id"]]["error"],
        })

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    if trace_rows:
        tp = Path(settings.rag_trace_path)
        tp.parent.mkdir(parents=True, exist_ok=True)
        with tp.open("w") as f:
            for t in trace_rows:
                f.write(json.dumps(t) + "\n")
        mean_tok = sum(t["approx_prompt_tokens"] for t in trace_rows) / len(trace_rows)
        mean_rlat = sum(t["retrieval_latency_ms"] for t in trace_rows) / len(trace_rows)
        print(f"\nRAG efficiency: mean prompt ~{mean_tok:,.0f} tokens (approx, chars/4)  "
              f"retrieval {mean_rlat:.0f} ms/q  -> traces {tp}")

    _summary(rows, per_run_overall, runs, out_path)


def _mean_std(vals: list[float]) -> str:
    m = 100 * statistics.mean(vals)
    if len(vals) < 2:
        return f"{m:5.1f}%"
    return f"{m:5.1f}% +/- {100 * statistics.stdev(vals):.1f}"


def _summary(rows, per_run_overall, runs, out_path) -> None:
    n = len(rows)
    print("\n" + "=" * 60)
    if runs > 1:
        print(f"OVERALL (n={n}, runs={runs})   "
              f"EX={_mean_std([r['ex'] for r in per_run_overall])}   "
              f"VER={_mean_std([r['ver'] for r in per_run_overall])}")
        flaky = [r for r in rows if 0 < r["ex_rate"] < 1]
        if flaky:
            tags = ", ".join(f"#{r['id']}({r['ex_passes']}/{runs})" for r in flaky)
            print(f"flaky (EX not stable across runs): {tags}")
    else:
        ex = sum(r["ex_passes"] for r in rows)
        ver = sum(r["ver_passes"] for r in rows)
        em = sum(r["em_passes"] for r in rows)
        print(f"OVERALL (n={n})   EX={100*ex/n:5.1f}%  VER={100*ver/n:5.1f}%  EM={100*em/n:5.1f}%")
    print("=" * 60)

    for key in ("difficulty", "module", "category"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        print(f"\nby {key}:")
        for g, grp in sorted(groups.items()):
            gn = len(grp)
            ex_rate = sum(r["ex_rate"] for r in grp) / gn
            ver_rate = sum(r["ver_rate"] for r in grp) / gn
            print(f"  {g:12} n={gn:2}  EX={100*ex_rate:5.1f}%  VER={100*ver_rate:5.1f}%")

    print(f"\nWrote {n} rows -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="evaluation/test_questions.json")
    ap.add_argument("--output", default="evaluation/results/baseline.csv")
    ap.add_argument("--runs", type=int, default=1, help="repeat N times, report mean +/- std")
    ap.add_argument("--rag", action="store_true", help="use the RAG pipeline instead of baseline")
    ap.add_argument("--rag-mode", default="both", choices=["fewshot", "schema", "both"])
    ap.add_argument("--retrieval-mode", default=None, choices=["semantic", "hybrid"],
                    help="override settings.rag_retrieval_mode for this run (RAG only)")
    ap.add_argument("--rag-top-k", type=int, default=None,
                    help="override settings.rag_top_k_fewshots for this run (RAG only)")
    args = ap.parse_args()
    run(args.test, args.output, args.runs, rag=args.rag, rag_mode=args.rag_mode,
        retrieval_mode=args.retrieval_mode, rag_top_k=args.rag_top_k)


if __name__ == "__main__":
    main()
