"""Layer-1 intrinsic SCHEMA-retrieval eval (RAG_plan §3.5) — CPU only, no LLM, no tunnel.

The schema half of the intrinsic study (the few-shot half is `intrinsic_eval.py`).
Scores `SchemaIndexer.retrieve_tables` against the 172 eval questions using the
**gold table set parsed from each question's gold_sql** as IR ground-truth (offline,
not a deployment signal). For each eval question it retrieves top-k table blocks and
measures schema-linking recall.

Metrics per config (k × always-core):
- table-recall@k    — |retrieved ∩ gold_tables| / |gold_tables|, mean over questions
- full-coverage@k   — fraction of questions where ALL gold tables are retrieved
- decode-coverage   — for decode questions, fraction where common.mst_* is retrieved
                      (the documented weak spot: decode tables rank below top-k)
- mean #tables      — mean retrieved-block count (prompt-cost proxy)

Picks/justifies the schema top-k and always-core setting BEFORE any HPC spend, and is
itself the schema half of the thesis intrinsic results section.

Run:
    python evaluation/intrinsic_schema_eval.py
    python evaluation/intrinsic_schema_eval.py --ks 3 5 --always-core on off
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import get_settings
from core.schema_extractor import SchemaExtractor
from core.schema_indexer import SchemaIndexer
from database.connection import get_engine

EVAL = Path(__file__).resolve().parent / "test_questions.json"
RESULTS = Path(__file__).resolve().parent / "results"

# schema-qualified table refs in gold_sql: <schema>.<table> after FROM/JOIN.
_TABLE_RE = re.compile(r"(?:from|join)\s+([a-z_][a-z_0-9]*\.[a-z_][a-z_0-9]*)", re.IGNORECASE)


def _gold_tables(sql: str) -> set[str]:
    return {m.lower() for m in _TABLE_RE.findall(sql)}


def _retrieved_names(blocks: list[str]) -> list[str]:
    names = []
    for b in blocks:
        head = b.split("\n", 1)[0]
        m = re.match(r"Table:\s+(\S+)", head)
        if m:
            names.append(m.group(1).lower())
    return names


def _eval_one_config(eval_items, indexer, settings, k, always_core):
    settings.rag_always_include_core_tables = always_core
    rows = []
    for it in eval_items:
        gold = _gold_tables(it["gold_sql"])
        blocks = indexer.retrieve_tables(it["question"], k)
        retr = set(_retrieved_names(blocks))
        hit = gold & retr
        recall = len(hit) / len(gold) if gold else 1.0
        full = int(gold <= retr) if gold else 1
        decode_tabs = {t for t in gold if t.startswith("common.")}
        decode_cov = None
        if decode_tabs:
            decode_cov = int(decode_tabs <= retr)
        rows.append({
            "id": it["id"], "category": it["category"], "module": it["module"],
            "n_gold": len(gold), "n_retrieved": len(blocks),
            "recall": round(recall, 4), "full_cover": full,
            "decode_cov": "" if decode_cov is None else decode_cov,
            "gold_tables": "|".join(sorted(gold)),
            "missed": "|".join(sorted(gold - retr)),
        })
    return rows


def _summary(tag, rows, k, always_core):
    n = len(rows)
    recall = 100 * sum(r["recall"] for r in rows) / n
    full = 100 * sum(r["full_cover"] for r in rows) / n
    mean_tabs = sum(r["n_retrieved"] for r in rows) / n
    dec = [r for r in rows if r["decode_cov"] != ""]
    dec_cov = (100 * sum(int(r["decode_cov"]) for r in dec) / len(dec)) if dec else float("nan")
    print(f"\n[{tag}]  k={k}  always_core={'on' if always_core else 'off'}  n={n}")
    print(f"  table-recall@k = {recall:5.1f}%   full-coverage@k = {full:5.1f}%   "
          f"decode-coverage = {dec_cov:5.1f}% (n={len(dec)})   mean #tables = {mean_tabs:.1f}")
    by_mod: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_mod[r["module"]].append(r)
    print("  by module (full-coverage@k):")
    for m, grp in sorted(by_mod.items()):
        h = 100 * sum(r["full_cover"] for r in grp) / len(grp)
        print(f"    {m:10} n={len(grp):2}  {h:5.1f}%")
    return {"tag": tag, "k": k, "always_core": always_core,
            "recall": recall, "full": full, "decode_cov": dec_cov, "mean_tabs": mean_tabs}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", default=str(EVAL))
    ap.add_argument("--ks", nargs="+", type=int, default=[3, 5])
    ap.add_argument("--always-core", nargs="+", default=["on", "off"])
    args = ap.parse_args()

    eval_items = json.loads(Path(args.eval).read_text())
    RESULTS.mkdir(parents=True, exist_ok=True)

    settings = get_settings()
    engine = get_engine(settings.database_url, read_only=True)
    extractor = SchemaExtractor(engine, settings.descriptions_path)
    indexer = SchemaIndexer(extractor, settings)
    indexer.load_or_build()

    summaries = []
    for ac in args.always_core:
        always_core = ac == "on"
        for k in args.ks:
            tag = f"schema_k{k}_core{'on' if always_core else 'off'}"
            rows = _eval_one_config(eval_items, indexer, settings, k, always_core)
            out = RESULTS / f"intrinsic_{tag}.csv"
            with out.open("w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                w.writeheader()
                w.writerows(rows)
            summaries.append(_summary(tag, rows, k, always_core))
            print(f"  -> {out}")

    print("\n" + "=" * 80)
    print(f"{'config':28} {'recall@k':>9} {'full@k':>8} {'decode':>8} {'#tables':>8}")
    for s in sorted(summaries, key=lambda x: (-x["full"], -x["recall"])):
        print(f"{s['tag']:28} {s['recall']:8.1f}% {s['full']:7.1f}% {s['decode_cov']:7.1f}% {s['mean_tabs']:8.1f}")
    print("Winner = highest full-coverage@k (tie-break recall), balanced vs prompt-cost (#tables).")


if __name__ == "__main__":
    main()
