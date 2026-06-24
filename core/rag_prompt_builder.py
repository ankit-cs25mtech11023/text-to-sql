"""RAGPromptBuilder — per-question prompt assembly (Phase 5-B).

Subclass of PromptBuilder kept in its own file so core/prompt_builder.py stays
byte-identical to main. Overrides build_messages to assemble the prompt per question
from retrieved context; inherits build_correction_messages unchanged (it only appends
the error turn to prior_messages, which already carry the RAG system prompt).

Modes (RAG_plan §5.4):
- fewshot : full static schema dump + RETRIEVED few-shot examples (cheap-signal cell)
- schema  : RETRIEVED table blocks, no few-shots
- both    : RETRIEVED table blocks + RETRIEVED few-shots (headline)

schema/both need a SchemaIndexer-backed retriever (wired in step 7); until then they
raise so a misconfigured run fails loudly instead of emitting an empty schema block.
"""

from __future__ import annotations

from config.prompts import SYSTEM_PROMPT_TEMPLATE, USER_PROMPT_TEMPLATE
from config.rag_prompts import (
    RAG_SYSTEM_PROMPT_TEMPLATE,
    format_retrieved_fewshots,
    format_retrieved_schema,
)
from config.settings import Settings
from core.prompt_builder import PromptBuilder
from core.rag_retriever import RAGRetriever

_RAG_MODES = {"fewshot", "schema", "both"}


class RAGPromptBuilder(PromptBuilder):
    def __init__(
        self,
        schema_context: dict[str, str],
        retriever: RAGRetriever,
        settings: Settings,
        mode: str = "both",
    ) -> None:
        if mode not in _RAG_MODES:
            raise ValueError(f"rag mode must be one of {_RAG_MODES}, got {mode!r}")
        if mode in {"schema", "both"} and not retriever.has_schema_index:
            raise NotImplementedError(
                "schema/both modes need a SchemaIndexer-backed retriever (Phase 5-B "
                "step 7); use mode='fewshot' until then"
            )
        # Deliberately NOT calling super().__init__ — no static system prompt is prebuilt.
        self._ctx = schema_context
        self._retriever = retriever
        self._settings = settings
        self._mode = mode

    def build_messages(self, question: str) -> list[dict]:
        r = self._retriever.retrieve(question)
        fewshots = (
            format_retrieved_fewshots(r["fewshots"])
            if self._mode in {"fewshot", "both"}
            else "(omitted in schema-only mode)"
        )

        if self._mode == "fewshot":
            system = SYSTEM_PROMPT_TEMPLATE.format(
                ddl=self._ctx["ddl"],
                descriptions=self._ctx["descriptions"],
                sample_rows=self._ctx["sample_rows"],
                few_shot_block=fewshots,
            )
        else:
            system = RAG_SYSTEM_PROMPT_TEMPLATE.format(
                retrieved_schema=format_retrieved_schema(r["tables"]),
                retrieved_fewshots=fewshots,
            )

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(question=question)},
        ]
