"""Distinguishability audit for EX on the toy DB (thesis_review.md W1 / §6.1).

For each gold question, systematically perturb the gold SQL into plausible-WRONG
variants, execute them, and check whether they coincidentally return the gold
result set (judged by the exact execution_match used for EX, order_matters
respected). A variant that matches is a COLLISION: on this data the metric
cannot distinguish that wrong query from the right one. The headline number is
the fraction of questions with >=1 colliding variant — the tightness bound on
every reported EX figure.

Mutators (deterministic under --seed):
- column-swap : replace one referenced column with a different LLM-visible
                column of the same table and type category ("wrong column").
- filter-drop : remove one top-level WHERE predicate (BETWEEN-aware split), or
                the whole WHERE/HAVING clause ("dropped filter").
- table-swap  : replace one table with another described table that contains
                every column the query references from it ("wrong table of
                compatible shape" — e.g. a COUNT(*) landing on the wrong module).

Caveat for the write-up: a colliding variant is wrong-by-construction on
*schema semantics*, but a few mutations can be true logical equivalences
(e.g. dropping a filter that is implied by another); the CSV keeps every
variant's SQL so collisions can be manually classified.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import Engine, text

from config.settings import get_settings
from core.sql_executor import execute_sql
from database.connection import get_engine
from evaluation.metrics import _norm_sql, execution_match

_NUMERIC = {"smallint", "integer", "bigint", "numeric", "real", "double precision"}
_TEXT = {"character varying", "character", "text"}
_DATETIME = {"date", "timestamp without time zone", "timestamp with time zone", "time without time zone"}

_RESERVED = {"range", "current_date", "user", "order", "group", "limit", "offset", "desc", "asc", "end", "current_time", "current_timestamp"}

_KEYWORDS = {
    "select", "from", "where", "group", "by", "order", "having", "limit", "offset",
    "join", "inner", "left", "right", "full", "outer", "cross", "on", "as", "and",
    "or", "not", "in", "is", "null", "like", "ilike", "between", "exists", "case",
    "when", "then", "else", "end", "distinct", "union", "all", "with", "asc",
    "desc", "count", "sum", "avg", "min", "max", "round", "coalesce", "cast",
    "to_date", "to_char", "to_number", "extract", "substring", "trim", "upper",
    "lower", "length", "abs", "nullif", "interval", "integer", "numeric", "varchar",
    "text", "date", "float", "boolean", "true", "false", "over", "partition",
    "row_number", "rank", "dense_rank", "concat", "replace", "split_part", "public",
    "live_reports", "common",
}

_TABLE_RE = re.compile(r"\b(?:public|live_reports|common)\.[A-Za-z_]\w*")
_CLAUSE_END_RE = re.compile(r"\b(GROUP\s+BY|ORDER\s+BY|HAVING|LIMIT|UNION|OFFSET)\b", re.I)


def _quote_ident(col: str) -> str:
    if col != col.lower() or col in _RESERVED:
        return f'"{col}"'
    return col


def _type_category(data_type: str) -> str:
    if data_type in _NUMERIC:
        return "numeric"
    if data_type in _TEXT:
        return "text"
    if data_type in _DATETIME:
        return "datetime"
    return "other"


def _load_schema_map(engine: Engine, descriptions_path: Path) -> dict[str, dict[str, str]]:
    """qualified table -> {LLM-visible column: type category}."""
    described = json.loads(descriptions_path.read_text())
    schema_map: dict[str, dict[str, str]] = {}
    with engine.connect() as conn:
        for qualified, meta in described.items():
            schema, table = qualified.split(".")
            rows = conn.execute(
                text(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = :s AND table_name = :t"
                ),
                {"s": schema, "t": table},
            ).fetchall()
            visible = set(meta.get("columns", {}))
            schema_map[qualified] = {
                name: _type_category(dtype) for name, dtype in rows if name in visible
            }
    return schema_map


def _strip_literals(sql: str) -> str:
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _replace_ident(sql: str, old: str, new: str) -> str:
    """Word-boundary replace outside string literals; handles quoted idents."""
    parts = re.split(r"('(?:[^']|'')*')", sql)
    pat = re.compile(rf'"{re.escape(old)}"|\b{re.escape(old)}\b')
    for i in range(0, len(parts), 2):
        parts[i] = pat.sub(new, parts[i])
    return "".join(parts)


def _query_tables(sql: str) -> list[str]:
    seen: list[str] = []
    for t in _TABLE_RE.findall(sql):
        if t not in seen:
            seen.append(t)
    return seen


def _column_tokens(sql: str) -> list[str]:
    stripped = _strip_literals(sql)
    tokens = re.findall(r'"([A-Za-z_]\w*)"|\b([a-z_]\w*)\b', stripped)
    out: list[str] = []
    for quoted, bare in tokens:
        tok = quoted or bare
        if tok and tok not in _KEYWORDS and tok not in out:
            out.append(tok)
    return out


def mutate_column_swap(
    sql: str, schema_map: dict[str, dict[str, str]], rng: random.Random, cap: int
) -> list[tuple[str, str]]:
    tables = [t for t in _query_tables(sql) if t in schema_map]
    table_basenames = {t.split(".")[1] for t in tables}
    variants: list[tuple[str, str]] = []
    for tok in _column_tokens(sql):
        if tok in table_basenames:
            continue
        owners = [t for t in tables if tok in schema_map[t]]
        if len(owners) != 1:
            continue
        cols = schema_map[owners[0]]
        cat = cols[tok]
        if cat == "other":
            continue
        candidates = sorted(c for c, cc in cols.items() if c != tok and cc == cat)
        if not candidates:
            continue
        repl = rng.choice(candidates)
        variants.append((f"col {tok}->{repl}", _replace_ident(sql, tok, _quote_ident(repl))))
    if len(variants) > cap:
        variants = rng.sample(variants, cap)
    return variants


def _find_clause(sql: str, keyword: str) -> tuple[int, int] | None:
    """(start, end) of the top-level clause body after `keyword`, or None."""
    depth = 0
    i = 0
    n = len(sql)
    kw = keyword.lower()
    while i < n:
        c = sql[i]
        if c == "'":
            j = sql.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and sql[i : i + len(kw)].lower() == kw:
            before_ok = i == 0 or not (sql[i - 1].isalnum() or sql[i - 1] == "_")
            after = i + len(kw)
            after_ok = after >= n or not (sql[after].isalnum() or sql[after] == "_")
            if before_ok and after_ok:
                body_start = after
                end = n
                for m in _CLAUSE_END_RE.finditer(sql, body_start):
                    if _depth_at(sql, m.start()) == 0:
                        end = m.start()
                        break
                return body_start, end
        i += 1
    return None


def _depth_at(sql: str, pos: int) -> int:
    depth = 0
    i = 0
    while i < pos:
        c = sql[i]
        if c == "'":
            j = sql.find("'", i + 1)
            i = len(sql) if j < 0 else j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        i += 1
    return depth


def _split_top_and(body: str) -> list[str]:
    """Split on top-level AND, keeping BETWEEN ... AND ... intact."""
    parts: list[str] = []
    depth = 0
    i = 0
    last = 0
    pending_between = 0
    n = len(body)
    while i < n:
        c = body[i]
        if c == "'":
            j = body.find("'", i + 1)
            i = n if j < 0 else j + 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif depth == 0 and body[i : i + 7].upper() == "BETWEEN":
            pending_between += 1
        elif depth == 0 and body[i : i + 3].upper() == "AND":
            before_ok = i == 0 or body[i - 1] in " )\n\t"
            after_ok = i + 3 >= n or body[i + 3] in " (\n\t"
            if before_ok and after_ok:
                if pending_between:
                    pending_between -= 1
                else:
                    parts.append(body[last:i])
                    last = i + 3
                    i += 3
                    continue
        i += 1
    parts.append(body[last:])
    return [p.strip() for p in parts if p.strip()]


def mutate_filter_drop(sql: str, cap: int) -> list[tuple[str, str]]:
    variants: list[tuple[str, str]] = []
    span = _find_clause(sql, "where")
    if span:
        start, end = span
        head, body, tail = sql[: start - 5], sql[start:end], sql[end:]
        preds = _split_top_and(body)
        if len(preds) == 1:
            variants.append(("drop WHERE", f"{head} {tail}".strip()))
        else:
            for k in range(len(preds)):
                kept = " AND ".join(p for j, p in enumerate(preds) if j != k)
                variants.append((f"drop pred #{k + 1}: {preds[k][:40]}", f"{head}WHERE {kept} {tail}"))
    hspan = _find_clause(sql, "having")
    if hspan:
        start, end = hspan
        variants.append(("drop HAVING", f"{sql[: start - 6]} {sql[end:]}".strip()))
    return variants[:cap] if cap else variants


def mutate_table_swap(
    sql: str, schema_map: dict[str, dict[str, str]], rng: random.Random, cap: int
) -> list[tuple[str, str]]:
    tables = [t for t in _query_tables(sql) if t in schema_map]
    tokens = set(_column_tokens(sql))
    variants: list[tuple[str, str]] = []
    for t in tables:
        referenced = tokens & set(schema_map[t])
        candidates = sorted(
            u
            for u, ucols in schema_map.items()
            if u != t and u not in tables and referenced <= set(ucols)
        )
        if not candidates:
            continue
        for u in rng.sample(candidates, min(len(candidates), max(1, cap // len(tables)))):
            variants.append((f"table {t.split('.')[1]}->{u.split('.')[1]}", sql.replace(t, u)))
    if len(variants) > cap:
        variants = rng.sample(variants, cap)
    return variants


def run_audit(
    questions_path: Path,
    out_path: Path,
    seed: int,
    caps: dict[str, int],
    limit: int,
) -> None:
    settings = get_settings()
    engine = get_engine(
        settings.database_url,
        read_only=True,
        statement_timeout_seconds=settings.query_timeout_seconds,
    )
    schema_map = _load_schema_map(engine, Path(settings.descriptions_path))
    items = json.loads(questions_path.read_text())

    rows: list[dict] = []
    per_q: dict[int, dict] = {}
    mut_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"generated": 0, "ran": 0, "matched": 0})

    for it in items:
        qid = it["id"]
        gold_sql = it["gold_sql"]
        order_matters = it.get("order_matters", False)
        rng = random.Random(seed + qid)
        gold = execute_sql(gold_sql, engine, limit=limit)
        if not gold.success:
            print(f"  !! gold #{qid} failed to execute: {gold.error}")
            continue

        variants: list[tuple[str, str, str]] = []
        for mutator, fn in (
            ("column-swap", lambda: mutate_column_swap(gold_sql, schema_map, rng, caps["column-swap"])),
            ("filter-drop", lambda: mutate_filter_drop(gold_sql, caps["filter-drop"])),
            ("table-swap", lambda: mutate_table_swap(gold_sql, schema_map, rng, caps["table-swap"])),
        ):
            for note, vsql in fn():
                variants.append((mutator, note, vsql))

        seen_norm = {_norm_sql(gold_sql)}
        n_ran = n_matched = 0
        for mutator, note, vsql in variants:
            norm = _norm_sql(vsql)
            if norm in seen_norm:
                continue
            seen_norm.add(norm)
            mut_stats[mutator]["generated"] += 1
            res = execute_sql(vsql, engine, limit=limit)
            matched = False
            if res.success:
                mut_stats[mutator]["ran"] += 1
                n_ran += 1
                matched = execution_match(gold.data, res.data, order_matters=order_matters)
                if matched:
                    mut_stats[mutator]["matched"] += 1
                    n_matched += 1
            rows.append(
                {
                    "id": qid,
                    "module": it["module"],
                    "difficulty": it["difficulty"],
                    "category": it["category"],
                    "mutator": mutator,
                    "note": note,
                    "runs_ok": int(res.success),
                    "matched": int(matched),
                    "error": (res.error or "")[:120],
                    "variant_sql": vsql,
                    "gold_sql": gold_sql,
                }
            )
        per_q[qid] = {
            "module": it["module"],
            "difficulty": it["difficulty"],
            "n_variants": len([r for r in rows if r["id"] == qid]),
            "n_ran": n_ran,
            "n_matched": n_matched,
        }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    _print_summary(per_q, mut_stats, rows, out_path)


def _print_summary(
    per_q: dict[int, dict],
    mut_stats: dict[str, dict[str, int]],
    rows: list[dict],
    out_path: Path,
) -> None:
    total_q = len(per_q)
    audited = {q: s for q, s in per_q.items() if s["n_ran"] > 0}
    colliding = {q: s for q, s in audited.items() if s["n_matched"] > 0}

    print(f"\n=== Distinguishability audit ({total_q} questions) ===")
    print(f"variants: {sum(s['generated'] for s in mut_stats.values())} generated, "
          f"{sum(s['ran'] for s in mut_stats.values())} ran, "
          f"{sum(s['matched'] for s in mut_stats.values())} matched gold")
    print(f"\nquestions with >=1 runnable wrong variant: {len(audited)}/{total_q}")
    print(f"questions with >=1 COLLISION:              {len(colliding)}/{len(audited)} "
          f"({100 * len(colliding) / max(1, len(audited)):.1f}%)")

    print("\nper mutator (matched / ran / generated):")
    for m, s in sorted(mut_stats.items()):
        rate = 100 * s["matched"] / max(1, s["ran"])
        print(f"  {m:12s} {s['matched']:4d} / {s['ran']:4d} / {s['generated']:4d}   ({rate:.1f}% of runnable)")

    for dim in ("module", "difficulty"):
        agg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
        for s in audited.values():
            agg[s[dim]][0] += 1
            if s["n_matched"] > 0:
                agg[s[dim]][1] += 1
        print(f"\ncollision rate by {dim}:")
        for k, (n, c) in sorted(agg.items()):
            print(f"  {k:12s} {c}/{n} ({100 * c / n:.1f}%)")

    if colliding:
        print(f"\ncolliding question ids: {sorted(colliding)}")
    print(f"\nfull per-variant report -> {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--questions", default="evaluation/test_questions.json")
    parser.add_argument("--out", default="evaluation/results/distinguishability_audit.csv")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--cap-column-swap", type=int, default=3)
    parser.add_argument("--cap-filter-drop", type=int, default=3)
    parser.add_argument("--cap-table-swap", type=int, default=2)
    args = parser.parse_args()

    run_audit(
        Path(args.questions),
        Path(args.out),
        args.seed,
        {
            "column-swap": args.cap_column_swap,
            "filter-drop": args.cap_filter_drop,
            "table-swap": args.cap_table_swap,
        },
        args.limit,
    )


if __name__ == "__main__":
    main()
