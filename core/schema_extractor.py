import json
from pathlib import Path

from sqlalchemy import Engine, inspect, text

# PostgreSQL reserved words / case-sensitive names that must be double-quoted
# when referenced. Case-sensitive names (InvVal, QtyUqc) are handled by the
# uppercase check in _quote_ident; this set covers reserved lowercase names.
_RESERVED = {
    "range", "current_date", "user", "order", "group", "table", "check",
    "all", "desc", "asc", "end", "default", "column", "references",
    "primary", "foreign", "select", "where", "from", "limit",
}


class SchemaExtractor:
    """Builds LLM schema context from the live DB across multiple PostgreSQL
    schemas. The set of tables exposed to the LLM is driven by the keys of the
    descriptions JSON (schema-qualified, e.g. 'public.tbl_gst_rtn_r3b'), which
    keeps DDL/sample-rows aligned with descriptions and automatically excludes
    partition children and LLM-HIDE columns."""

    def __init__(
        self,
        engine: Engine,
        descriptions_path: str | Path,
        max_cols_for_samples: int = 40,
    ) -> None:
        self._engine = engine
        self._descriptions: dict = json.loads(Path(descriptions_path).read_text())
        self._inspector = inspect(engine)
        self._max_cols_for_samples = max_cols_for_samples

        # Parse each descriptions key into (qualified, schema, table).
        self._tables: list[tuple[str, str, str]] = []
        for qualified in self._descriptions:
            if "." in qualified:
                schema, table = qualified.split(".", 1)
            else:
                schema, table = "public", qualified
            self._tables.append((qualified, schema, table))

    def _quote_ident(self, name: str) -> str:
        if name != name.lower() or name.lower() in _RESERVED:
            return f'"{name}"'
        return name

    def get_allowed_table_names(self) -> set[str]:
        """Lowercased table names accepted by the validator. Includes both the
        schema-qualified form (public.tbl_x) and the bare form (tbl_x) so a
        query passes whether or not the LLM schema-qualifies — the executor is
        the final arbiter for unqualified names not on the search_path."""
        names: set[str] = set()
        for qualified, _schema, table in self._tables:
            names.add(qualified.lower())
            names.add(table.lower())
        return names

    def get_ddl(self) -> str:
        lines: list[str] = []
        for qualified, schema, table in self._tables:
            desc_cols = self._descriptions[qualified].get("columns", {})
            try:
                cols = self._inspector.get_columns(table, schema=schema)
                fks = self._inspector.get_foreign_keys(table, schema=schema)
            except Exception:
                continue
            fk_map = {
                fk["constrained_columns"][0]: fk
                for fk in fks
                if fk["constrained_columns"]
            }

            lines.append(f"CREATE TABLE {schema}.{table} (")
            col_lines: list[str] = []
            for col in cols:
                if col["name"] not in desc_cols:
                    continue  # respect LLM-HIDE columns + partition noise
                col_type = str(col["type"])
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                fk_clause = ""
                if col["name"] in fk_map:
                    fk = fk_map[col["name"]]
                    ref_schema = fk.get("referred_schema") or "public"
                    fk_clause = (
                        f" REFERENCES {ref_schema}.{fk['referred_table']}"
                        f"({fk['referred_columns'][0]})"
                    )
                col_lines.append(
                    f"  {self._quote_ident(col['name'])} {col_type}{nullable}{fk_clause}"
                )
            lines.append(",\n".join(col_lines))
            lines.append(");\n")
        return "\n".join(lines)

    def get_column_descriptions(self) -> str:
        lines: list[str] = []
        for qualified, _schema, _table in self._tables:
            meta = self._descriptions[qualified]
            lines.append(f"-- {qualified}: {meta.get('table_description', '')}")
            for col, desc in meta.get("columns", {}).items():
                lines.append(f"  {qualified}.{col}: {desc}")
            lines.append("")
        return "\n".join(lines)

    def get_sample_rows(self, n: int = 3) -> str:
        lines: list[str] = []
        with self._engine.connect() as conn:
            for qualified, schema, table in self._tables:
                desc_cols = list(self._descriptions[qualified].get("columns", {}).keys())
                if not desc_cols or len(desc_cols) > self._max_cols_for_samples:
                    continue
                col_sql = ", ".join(self._quote_ident(c) for c in desc_cols)
                try:
                    rows = conn.execute(
                        text(f"SELECT {col_sql} FROM {schema}.{table} LIMIT {n}")
                    ).fetchall()
                except Exception:
                    continue
                if not rows:
                    continue
                lines.append(f"-- {schema}.{table}")
                lines.append("  " + " | ".join(desc_cols))
                for row in rows:
                    lines.append("  " + " | ".join(str(v) for v in row))
                lines.append("")
        return "\n".join(lines)

    def get_table_blocks(self) -> dict[str, str]:
        """One M-Schema text block per table (qualified name -> block) for schema
        retrieval (Phase 5-B). Reuses the same column/FK/description logic as
        get_ddl; LLM-HIDE columns (absent from descriptions) are excluded.
        Each column line carries up to 3 distinct live values ("Examples: [...]"),
        matching the M-Schema format XiYanSQL was trained on — restores the value
        grounding that sample rows give the static prompt (categorical filters,
        entity routing) and lets value-bearing questions match their table at
        retrieval time."""
        blocks: dict[str, str] = {}
        with self._engine.connect() as conn:
            for qualified, schema, table in self._tables:
                meta = self._descriptions[qualified]
                desc_cols = meta.get("columns", {})
                try:
                    cols = self._inspector.get_columns(table, schema=schema)
                    fks = self._inspector.get_foreign_keys(table, schema=schema)
                except Exception:
                    continue
                fk_map = {
                    fk["constrained_columns"][0]: fk
                    for fk in fks
                    if fk["constrained_columns"]
                }
                header = f"Table: {qualified}"
                tdesc = meta.get("table_description", "")
                if tdesc:
                    header += f" — {tdesc}"
                lines = [header]
                for col in cols:
                    name = col["name"]
                    if name not in desc_cols:
                        continue
                    note = desc_cols.get(name, "")
                    if name in fk_map:
                        fk = fk_map[name]
                        ref_schema = fk.get("referred_schema") or "public"
                        ref = f"{ref_schema}.{fk['referred_table']}.{fk['referred_columns'][0]}"
                        note = f"{note} (FK -> {ref})" if note else f"FK -> {ref}"
                    line = f"  {self._quote_ident(name)} ({col['type']})"
                    if name not in fk_map:
                        ex = self._column_examples(conn, schema, table, name)
                        if ex:
                            line += f" Examples: [{ex}]"
                    if note:
                        line += f" -- {note}"
                    lines.append(line)
                blocks[qualified] = "\n".join(lines)
        return blocks

    def _column_examples(self, conn, schema: str, table: str, name: str) -> str:
        # Surrogate PKs carry no semantic value — skip (FK columns skipped by caller).
        if name == "id" or name.startswith("idtbl"):
            return ""
        q = self._quote_ident(name)
        try:
            rows = conn.execute(
                text(
                    f"SELECT DISTINCT {q} FROM {schema}.{table} "
                    f"WHERE {q} IS NOT NULL ORDER BY {q} LIMIT 3"
                )
            ).fetchall()
        except Exception:
            conn.rollback()  # a failed SELECT aborts the PG transaction — clear it
            return ""
        vals: list[str] = []
        for (v,) in rows:
            s = v if isinstance(v, str) else str(v)
            if len(s) > 40:
                s = s[:37] + "..."
            vals.append(repr(s) if isinstance(v, str) else s)
        return ", ".join(vals)

    def get_fk_parents(self) -> dict[str, list[str]]:
        """Qualified child -> qualified FK-parent tables, restricted to described
        tables. Used by SchemaIndexer's FK-closure injection (retrieval misses
        semantically-bland bridge tables; the closure re-adds them)."""
        known = {q for q, _s, _t in self._tables}
        parents: dict[str, list[str]] = {}
        for qualified, schema, table in self._tables:
            try:
                fks = self._inspector.get_foreign_keys(table, schema=schema)
            except Exception:
                continue
            ps: list[str] = []
            for fk in fks:
                ref = f"{fk.get('referred_schema') or 'public'}.{fk['referred_table']}"
                if ref in known and ref != qualified and ref not in ps:
                    ps.append(ref)
            if ps:
                parents[qualified] = ps
        return parents

    def get_full_context(self, sample_n: int = 1) -> dict[str, str]:
        # sample_n=1 (not 3): the normalized 39-table schema pushed the static
        # prompt past the 32K window (n=3 ~33K, n=2 32.5K — no room for output).
        # ~4.9K tokens per sample-row-set across 39 tables. One row per table still
        # grounds column formats (and descriptions already carry inline "Sample:"
        # values), leaving ~2.6K headroom for the 1024-token output + self-correction
        # turns. RAG configs use retrieved schema, not this block.
        return {
            "ddl": self.get_ddl(),
            "descriptions": self.get_column_descriptions(),
            "sample_rows": self.get_sample_rows(sample_n),
        }
