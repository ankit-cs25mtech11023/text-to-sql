from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine

from config.settings import Settings
from core.llm_client import make_client
from core.prompt_builder import PromptBuilder
from core.schema_extractor import SchemaExtractor
from core.self_correction import CorrectionResult, run_with_correction
from core.sql_generator import SQLGenerator
from database.connection import get_engine


@dataclass
class PipelineResult:
    success: bool
    question: str
    sql: str
    data: pd.DataFrame | None = None
    error: str | None = None
    attempts: int = 0
    execution_time_ms: float = 0.0


class TextToSQLPipeline:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._engine: Engine = get_engine(
            settings.database_url,
            read_only=True,
            statement_timeout_seconds=settings.query_timeout_seconds,
        )
        extractor = SchemaExtractor(self._engine, settings.descriptions_path)
        ctx = extractor.get_full_context()
        self._allowed_tables: set[str] = extractor.get_allowed_table_names()

        builder = PromptBuilder(ctx, few_shot_n=settings.few_shot_examples)
        llm = make_client(
            provider=settings.default_provider,
            model=settings.default_model,
            base_url=settings.vllm_base_url,
            api_key=settings.vllm_api_key,
        )
        self._generator = SQLGenerator(llm, builder)

    def ask(self, question: str) -> PipelineResult:
        result: CorrectionResult = run_with_correction(
            question=question,
            generator=self._generator,
            engine=self._engine,
            allowed_tables=self._allowed_tables,
            max_attempts=self._settings.max_correction_attempts,
            temperature=self._settings.temperature,
            limit=self._settings.query_result_limit,
            max_tokens=self._settings.max_tokens,
        )
        return PipelineResult(
            success=result.success,
            question=question,
            sql=result.sql,
            data=result.data,
            error=result.error,
            attempts=result.attempts,
            execution_time_ms=result.execution_time_ms,
        )
