import json
from pathlib import Path

from sqlalchemy import Engine, inspect, text


class SchemaExtractor:
    def __init__(self, engine: Engine, descriptions_path: str | Path) -> None:
        self._engine = engine
        self._descriptions: dict = json.loads(Path(descriptions_path).read_text())
        self._inspector = inspect(engine)

    def get_ddl(self) -> str:
        lines: list[str] = []
        for table_name in self._inspector.get_table_names():
            cols = self._inspector.get_columns(table_name)
            fks = self._inspector.get_foreign_keys(table_name)
            fk_map = {fk["constrained_columns"][0]: fk for fk in fks if fk["constrained_columns"]}

            lines.append(f"CREATE TABLE {table_name} (")
            col_lines = []
            for col in cols:
                col_type = str(col["type"])
                nullable = "" if col.get("nullable", True) else " NOT NULL"
                default = f" DEFAULT {col['default']}" if col.get("default") is not None else ""
                fk_clause = ""
                if col["name"] in fk_map:
                    fk = fk_map[col["name"]]
                    fk_clause = f" REFERENCES {fk['referred_table']}({fk['referred_columns'][0]})"
                col_lines.append(f"  {col['name']} {col_type}{nullable}{default}{fk_clause}")
            lines.append(",\n".join(col_lines))
            lines.append(");\n")
        return "\n".join(lines)

    def get_column_descriptions(self) -> str:
        lines: list[str] = []
        for table, meta in self._descriptions.items():
            lines.append(f"-- {table}: {meta.get('table_description', '')}")
            for col, desc in meta.get("columns", {}).items():
                lines.append(f"  {table}.{col}: {desc}")
            lines.append("")
        return "\n".join(lines)

    def get_sample_rows(self, n: int = 3) -> str:
        lines: list[str] = []
        with self._engine.connect() as conn:
            for table_name in self._inspector.get_table_names():
                rows = conn.execute(text(f"SELECT * FROM {table_name} LIMIT {n}")).fetchall()
                if not rows:
                    continue
                cols = self._inspector.get_columns(table_name)
                col_names = [c["name"] for c in cols]
                lines.append(f"-- {table_name}")
                lines.append("  " + " | ".join(col_names))
                for row in rows:
                    lines.append("  " + " | ".join(str(v) for v in row))
                lines.append("")
        return "\n".join(lines)

    def get_full_context(self) -> dict[str, str]:
        return {
            "ddl": self.get_ddl(),
            "descriptions": self.get_column_descriptions(),
            "sample_rows": self.get_sample_rows(),
        }
