"""RAGTextToSQLPipeline — Phase 5-B drop-in extension of TextToSQLPipeline.

In its own file so core/pipeline.py stays byte-identical to main. Overrides only
__init__ (wires RAGRetriever + RAGPromptBuilder); ask() is inherited verbatim, so
validation / execution / self-correction are reused unchanged.
"""

from __future__ import annotations

from sqlalchemy import Engine

from config.settings import Settings
from core.llm_client import make_client
from core.pipeline import TextToSQLPipeline
from core.rag_prompt_builder import RAGPromptBuilder
from core.rag_retriever import RAGRetriever
from core.schema_extractor import SchemaExtractor
from core.sql_generator import SQLGenerator
from database.connection import get_engine


class RAGTextToSQLPipeline(TextToSQLPipeline):
    def __init__(
        self,
        settings: Settings,
        rag_mode: str = "both",
        retriever: RAGRetriever | None = None,
    ) -> None:
        self._settings = settings
        self._engine: Engine = get_engine(
            settings.database_url,
            read_only=True,
            statement_timeout_seconds=settings.query_timeout_seconds,
        )
        extractor = SchemaExtractor(self._engine, settings.descriptions_path)
        ctx = extractor.get_full_context()
        self._allowed_tables: set[str] = extractor.get_allowed_table_names()

        # schema-table retrieval is built only for modes that use it (schema/both);
        # fewshot mode keeps the full static schema, so no schema index is needed.
        schema_indexer = None
        if rag_mode in {"schema", "both"}:
            from core.schema_indexer import SchemaIndexer

            schema_indexer = SchemaIndexer(extractor, settings)
            schema_indexer.load_or_build()
        # retriever may be passed in so the embed model loads once across pipelines.
        self._retriever = retriever or RAGRetriever(settings, schema_indexer=schema_indexer)
        self._rag_mode = rag_mode
        builder = RAGPromptBuilder(ctx, self._retriever, settings, mode=rag_mode)
        llm = make_client(**settings.llm_client_kwargs())
        self._generator = SQLGenerator(llm, builder)
