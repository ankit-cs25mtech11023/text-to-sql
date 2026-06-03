from config.prompts import (
    SYSTEM_PROMPT_TEMPLATE,
    USER_PROMPT_TEMPLATE,
    CORRECTION_PROMPT_TEMPLATE,
    build_few_shot_block,
)


class PromptBuilder:
    def __init__(self, schema_context: dict[str, str], few_shot_n: int = 0) -> None:
        self._context = schema_context
        self._few_shot_n = few_shot_n
        self._system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            ddl=schema_context["ddl"],
            descriptions=schema_context["descriptions"],
            sample_rows=schema_context["sample_rows"],
            few_shot_block=build_few_shot_block(few_shot_n),
        )

    def build_messages(self, question: str) -> list[dict]:
        return [
            {"role": "system", "content": self._system_prompt},
            {"role": "user", "content": USER_PROMPT_TEMPLATE.format(question=question)},
        ]

    def build_correction_messages(
        self,
        question: str,
        bad_sql: str,
        error: str,
        prior_messages: list[dict],
    ) -> list[dict]:
        correction_user = CORRECTION_PROMPT_TEMPLATE.format(
            question=question,
            sql=bad_sql,
            error=error,
        )
        return [
            *prior_messages,
            {"role": "assistant", "content": bad_sql},
            {"role": "user", "content": correction_user},
        ]
