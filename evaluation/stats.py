"""Statistical treatment of benchmark results (thesis_review.md W4 / §6.3).

- Wilson 95% CIs on the headline EX/VER rates of every canonical result CSV.
- McNemar's test (EXACT binomial, two-sided) on paired per-question outcomes for
  the key config comparisons. Exact, not chi-square: discordant counts here are
  single digits, far below the chi-square approximation's validity.
- Every pair also lists WHICH question ids flipped — the review requires small
  deltas be reported as mechanism (traceable questions), not magnitude.

Per-question binarization over --runs repetitions: majority vote by default
(ex_passes*2 > runs), so a 2/3-flaky question (e.g. #62) counts by its typical
behavior; --binarize strict requires all runs to pass. All headline runs were
±0.0, so the choice only affects flaky questions.

Usage:
  python evaluation/stats.py                       # full report over canonical CSVs
  python evaluation/stats.py --pair A.csv B.csv    # ad-hoc McNemar for any two
"""
from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path

Z95 = 1.959963984540054

CANONICAL = [
    ("XiYan baseline", "baseline.csv"),
    ("XiYan schema-only", "rag_schema.csv"),
    ("XiYan few-shot", "rag_fewshot.csv"),
    ("XiYan full RAG", "rag.csv"),
    ("Qwen baseline", "qwen27b_baseline.csv"),
    ("Qwen schema-only", "qwen27b_rag_schema.csv"),
    ("Qwen few-shot", "qwen27b_rag_fewshot.csv"),
    ("Qwen full RAG", "qwen27b_rag.csv"),
]

KEY_PAIRS = [
    ("XiYan baseline", "XiYan full RAG"),
    ("XiYan baseline", "XiYan few-shot"),
    ("XiYan baseline", "XiYan schema-only"),
    ("XiYan few-shot", "XiYan full RAG"),
    ("Qwen baseline", "Qwen full RAG"),
    ("Qwen baseline", "Qwen schema-only"),
    ("XiYan baseline", "Qwen baseline"),
    ("XiYan full RAG", "Qwen full RAG"),
]


def wilson_ci(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, center - half), min(1.0, center + half)


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial p-value on the b/c discordant split."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def load_outcomes(path: Path, metric: str, binarize: str) -> dict[int, bool]:
    passes_col = f"{metric}_passes"
    out: dict[int, bool] = {}
    with path.open() as f:
        for row in csv.DictReader(f):
            k, runs = int(row[passes_col]), int(row["runs"])
            out[int(row["id"])] = (k == runs) if binarize == "strict" else (2 * k > runs)
    return out


def report_cis(configs: list[tuple[str, Path]], binarize: str) -> list[dict]:
    rows = []
    print(f"\n=== Wilson 95% CIs (per-question {binarize}-binarized) ===")
    print(f"{'config':<20} {'metric':<4} {'rate':>7} {'95% CI':>18}   k/n")
    for label, path in configs:
        for metric in ("ex", "ver"):
            outcomes = load_outcomes(path, metric, binarize)
            k, n = sum(outcomes.values()), len(outcomes)
            lo, hi = wilson_ci(k, n)
            print(f"{label:<20} {metric.upper():<4} {100*k/n:6.1f}% [{100*lo:5.1f}%, {100*hi:5.1f}%]   {k}/{n}")
            rows.append({
                "config": label, "file": path.name, "metric": metric.upper(),
                "k": k, "n": n, "rate": round(100 * k / n, 1),
                "ci_lo": round(100 * lo, 1), "ci_hi": round(100 * hi, 1),
            })
    return rows


def report_mcnemar(
    pairs: list[tuple[str, Path, str, Path]], metric: str, binarize: str
) -> list[dict]:
    rows = []
    print(f"\n=== McNemar exact (paired per-question {metric.upper()}) ===")
    print(f"{'A vs B':<42} {'b=A only':>8} {'c=B only':>8} {'p':>8}   flipped ids")
    for label_a, path_a, label_b, path_b in pairs:
        a = load_outcomes(path_a, metric, binarize)
        b_out = load_outcomes(path_b, metric, binarize)
        common = sorted(set(a) & set(b_out))
        if len(common) != len(a) or len(common) != len(b_out):
            print(f"  !! {label_a} vs {label_b}: id sets differ, using {len(common)} common")
        only_a = [q for q in common if a[q] and not b_out[q]]
        only_b = [q for q in common if b_out[q] and not a[q]]
        p = mcnemar_exact(len(only_a), len(only_b))
        flips = ""
        if only_a:
            flips += f"A-only={only_a} "
        if only_b:
            flips += f"B-only={only_b}"
        print(f"{label_a + ' vs ' + label_b:<42} {len(only_a):>8} {len(only_b):>8} {p:8.4f}   {flips or '-'}")
        rows.append({
            "a": label_a, "b": label_b, "metric": metric.upper(), "n": len(common),
            "a_only_wins": len(only_a), "b_only_wins": len(only_b),
            "p_exact": round(p, 4),
            "a_only_ids": " ".join(map(str, only_a)),
            "b_only_ids": " ".join(map(str, only_b)),
        })
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--results-dir", default="evaluation/results")
    parser.add_argument("--pair", nargs=2, metavar=("A_CSV", "B_CSV"),
                        help="ad-hoc McNemar between two result CSVs (paths)")
    parser.add_argument("--metric", choices=["ex", "ver"], default="ex")
    parser.add_argument("--binarize", choices=["majority", "strict"], default="majority")
    parser.add_argument("--out", default="evaluation/results/stats_mcnemar.csv")
    parser.add_argument("--out-ci", default="evaluation/results/stats_wilson_ci.csv")
    args = parser.parse_args()
    rdir = Path(args.results_dir)

    if args.pair:
        pa, pb = Path(args.pair[0]), Path(args.pair[1])
        report_mcnemar([(pa.stem, pa, pb.stem, pb)], args.metric, args.binarize)
        return

    configs = [(label, rdir / fname) for label, fname in CANONICAL if (rdir / fname).exists()]
    missing = [fname for _, fname in CANONICAL if not (rdir / fname).exists()]
    if missing:
        print(f"skipping missing: {missing}")
    by_label = dict(configs)

    ci_rows = report_cis(configs, args.binarize)
    pairs = [
        (la, by_label[la], lb, by_label[lb])
        for la, lb in KEY_PAIRS
        if la in by_label and lb in by_label
    ]
    mc_rows = report_mcnemar(pairs, args.metric, args.binarize)

    for out_path, rows in ((Path(args.out_ci), ci_rows), (Path(args.out), mc_rows)):
        with out_path.open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            writer.writeheader()
            writer.writerows(rows)
        print(f"-> {out_path}")


if __name__ == "__main__":
    main()
