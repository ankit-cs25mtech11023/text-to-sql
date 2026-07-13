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
        get_ddl; LLM-HIDE columns (absent from descriptions) are excluded."""
        blocks: dict[str, str] = {}
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
                if note:
                    line += f" -- {note}"
                lines.append(line)
            blocks[qualified] = "\n".join(lines)
        return blocks

    def get_full_context(self) -> dict[str, str]:
        return {
            "ddl": self.get_ddl(),
            "descriptions": self.get_column_descriptions(),
            "sample_rows": self.get_sample_rows(),
        }
