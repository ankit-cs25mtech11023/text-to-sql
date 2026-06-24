"""RAG-specific prompt assembly (Phase 5-B).

Kept separate from config/prompts.py so RAG prompt tweaking never risks the baseline
template. The shared general header (rules + HOW-TO-BUILD playbook + GST domain rules
+ quoting/date conventions) is DERIVED from the baseline SYSTEM_PROMPT_TEMPLATE by
slicing off the static schema dump — NOT copied. So the two can never diverge and
config/prompts.py stays byte-identical to main.
"""

from __future__ import annotations

from config.prompts import FEW_SHOT_HEADER, SYSTEM_PROMPT_TEMPLATE

_SCHEMA_MARKER = "\n\nDATABASE SCHEMA:"
assert _SCHEMA_MARKER in SYSTEM_PROMPT_TEMPLATE, (
    "baseline schema marker moved — update _SCHEMA_MARKER in config/rag_prompts.py"
)

# Everything in the baseline template before the static schema dump = the shared header.
SHARED_HEADER = SYSTEM_PROMPT_TEMPLATE.split(_SCHEMA_MARKER, 1)[0]

# Same header, but the full static schema is replaced by per-question retrieved context.
RAG_SYSTEM_PROMPT_TEMPLATE = SHARED_HEADER + """

RELEVANT TABLES (retrieved for this question):
{retrieved_schema}

SIMILAR SOLVED EXAMPLES (retrieved for this question):
{retrieved_fewshots}"""


def format_retrieved_fewshots(shots: list[dict]) -> str:
    if not shots:
        return "(none retrieved)"
    lines = [FEW_SHOT_HEADER]
    for s in shots:
        lines.append(f"Q: {s['question']}")
        lines.append(f"SQL: {s['gold_sql']}\n")
    return "\n".join(lines)


def format_retrieved_schema(blocks: list[str]) -> str:
    return "\n\n".join(blocks) if blocks else "(none retrieved)"
