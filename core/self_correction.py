from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine

from core.sql_executor import ExecutionResult, execute_sql
from core.sql_generator import SQLGenerator
from core.sql_validator import ValidationResult, validate_sql


@dataclass
class CorrectionResult:
    success: bool
    sql: str
    data: pd.DataFrame | None = None
    error: str | None = None
    attempts: int = 0
    execution_time_ms: float = 0.0


def run_with_correction(
    question: str,
    generator: SQLGenerator,
    engine: Engine,
    allowed_tables: set[str] | None = None,
    max_attempts: int = 3,
    temperature: float = 0.0,
    limit: int = 500,
) -> CorrectionResult:
    sql, messages = generator.generate(question, temperature=temperature)

    for attempt in range(1, max_attempts + 1):
        # Step 1: validate
        val: ValidationResult = validate_sql(sql, allowed_tables)
        if not val.valid:
            if attempt == max_attempts:
                return CorrectionResult(
                    success=False, sql=sql, error=val.error, attempts=attempt
                )
            sql = generator.generate_correction(
                question, sql, f"Validation error: {val.error}", messages, temperature=temperature
            )
            continue

        # Step 2: execute
        result: ExecutionResult = execute_sql(sql, engine, limit=limit)
        if result.success:
            return CorrectionResult(
                success=True,
                sql=sql,
                data=result.data,
                attempts=attempt,
                execution_time_ms=result.execution_time_ms,
            )

        if attempt == max_attempts:
            return CorrectionResult(
                success=False, sql=sql, error=result.error, attempts=attempt,
                execution_time_ms=result.execution_time_ms,
            )

        sql = generator.generate_correction(
            question, sql, f"Execution error: {result.error}", messages, temperature=temperature
        )

    return CorrectionResult(success=False, sql=sql, error="Max attempts reached.", attempts=max_attempts)
