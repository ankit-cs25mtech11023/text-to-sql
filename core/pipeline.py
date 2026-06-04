from dataclasses import dataclass

import pandas as pd
from sqlalchemy import Engine, inspect

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
            settings.database_url.replace("sqlite:///", ""), read_only=True
        )
        extractor = SchemaExtractor(self._engine, settings.descriptions_path)
        ctx = extractor.get_full_context()
        self._allowed_tables: set[str] = set(inspect(self._engine).get_table_names())

        builder = PromptBuilder(ctx, few_shot_n=settings.few_shot_examples)
        llm = make_client(settings.default_provider, self._api_key(settings), settings.default_model)
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

    @staticmethod
    def _api_key(settings: Settings) -> str:
        if settings.default_provider == "groq":
            return settings.groq_api_key
        return settings.openrouter_api_key
