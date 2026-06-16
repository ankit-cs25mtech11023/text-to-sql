"""Batch evaluation runner.

Runs every gold question through the pipeline, compares the predicted result to
the gold result, and writes per-question scores + a summary.

Usage:
    python evaluation/benchmark.py
    python evaluation/benchmark.py --test evaluation/test_questions.json \
                                   --output evaluation/results/baseline.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from core.pipeline import TextToSQLPipeline
from core.sql_executor import execute_sql
from database.connection import get_engine
from evaluation.metrics import exact_match, execution_match

FIELDS = [
    "id", "module", "difficulty", "category", "question",
    "gold_sql", "pred_sql", "ver", "ex", "em", "attempts", "time_ms", "error",
]


def run(test_path: str, out_path: str) -> list[dict]:
    settings = get_settings()
    pipeline = TextToSQLPipeline(settings)
    gold_engine = get_engine(
        settings.database_url,
        read_only=True,
        statement_timeout_seconds=settings.query_timeout_seconds,
    )
    items = json.loads(Path(test_path).read_text())
    rows: list[dict] = []

    for it in items:
        res = pipeline.ask(it["question"])
        gold = execute_sql(it["gold_sql"], gold_engine, limit=settings.query_result_limit)
        ver = res.success
        ex = (
            execution_match(gold.data, res.data, order_matters=it.get("order_matters", False))
            if ver and gold.success
            else False
        )
        em = exact_match(it["gold_sql"], res.sql)
        rows.append({
            "id": it["id"], "module": it["module"], "difficulty": it["difficulty"],
            "category": it["category"], "question": it["question"],
            "gold_sql": it["gold_sql"], "pred_sql": res.sql,
            "ver": int(ver), "ex": int(ex), "em": int(em),
            "attempts": res.attempts, "time_ms": round(res.execution_time_ms, 1),
            "error": (res.error or "") if not ver else "",
        })
        mark = "✓" if ex else ("~" if ver else "✗")
        print(f"  [{it['id']:2}] {mark} EX={int(ex)} VER={int(ver)} EM={int(em)} "
              f"att={res.attempts} {it['difficulty'][:4]:4} {it['module']:7} | {it['question'][:54]}")

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)

    _summary(rows, out_path)
    return rows


def _pct(num: int, den: int) -> str:
    return f"{100 * num / den:5.1f}%" if den else "  n/a"


def _summary(rows: list[dict], out_path: str) -> None:
    n = len(rows)
    ex, ver, em = sum(r["ex"] for r in rows), sum(r["ver"] for r in rows), sum(r["em"] for r in rows)
    print("\n" + "=" * 56)
    print(f"OVERALL (n={n})   EX={_pct(ex, n)}  VER={_pct(ver, n)}  EM={_pct(em, n)}")
    print("=" * 56)

    for key in ("difficulty", "module"):
        groups: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            groups[r[key]].append(r)
        print(f"\nby {key}:")
        for g, grp in sorted(groups.items()):
            gn = len(grp)
            print(f"  {g:12} n={gn:2}  EX={_pct(sum(r['ex'] for r in grp), gn)}  "
                  f"VER={_pct(sum(r['ver'] for r in grp), gn)}")

    print(f"\nWrote {n} rows -> {out_path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", default="evaluation/test_questions.json")
    ap.add_argument("--output", default="evaluation/results/baseline.csv")
    args = ap.parse_args()
    run(args.test, args.output)


if __name__ == "__main__":
    main()
