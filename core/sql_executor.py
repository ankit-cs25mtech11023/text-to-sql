import re
import time
from dataclasses import dataclass, field

import pandas as pd
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError


@dataclass
class ExecutionResult:
    success: bool
    data: pd.DataFrame | None = None
    error: str | None = None
    row_count: int = 0
    execution_time_ms: float = 0.0


def execute_sql(sql: str, engine: Engine, limit: int = 500) -> ExecutionResult:
    sql = _inject_limit(sql, limit)

    start = time.monotonic()
    try:
        with engine.connect() as conn:
            result = conn.execute(text(sql))
            rows = result.fetchall()
            columns = list(result.keys())

        elapsed_ms = (time.monotonic() - start) * 1000
        df = pd.DataFrame(rows, columns=columns)
        return ExecutionResult(
            success=True,
            data=df,
            row_count=len(df),
            execution_time_ms=round(elapsed_ms, 2),
        )

    except SQLAlchemyError as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        return ExecutionResult(
            success=False,
            error=str(e).split("\n")[0],  # first line only — avoid multi-line noise
            execution_time_ms=round(elapsed_ms, 2),
        )


def _inject_limit(sql: str, limit: int) -> str:
    # Don't add LIMIT if one already exists
    if re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        return sql
    sql = sql.rstrip().rstrip(";")
    return f"{sql} LIMIT {limit};"
