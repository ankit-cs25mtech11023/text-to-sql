import re

from core.llm_client import LLMClient
from core.prompt_builder import PromptBuilder


class SQLGenerator:
    def __init__(self, llm: LLMClient, prompt_builder: PromptBuilder) -> None:
        self._llm = llm
        self._prompt_builder = prompt_builder

    def generate(
        self,
        question: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> tuple[str, list[dict]]:
        messages = self._prompt_builder.build_messages(question)
        raw = self._llm.generate(messages, temperature=temperature, max_tokens=max_tokens)
        sql = self._extract_sql(raw)
        return sql, messages

    def generate_correction(
        self,
        question: str,
        bad_sql: str,
        error: str,
        prior_messages: list[dict],
        temperature: float = 0.0,
        max_tokens: int = 1024,
    ) -> str:
        messages = self._prompt_builder.build_correction_messages(
            question, bad_sql, error, prior_messages
        )
        raw = self._llm.generate(messages, temperature=temperature, max_tokens=max_tokens)
        return self._extract_sql(raw)

    def _extract_sql(self, text: str) -> str:
        # Strip markdown code fences if present
        fenced = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if fenced:
            return fenced.group(1).strip()

        # If no fence, return the raw text stripped of leading/trailing whitespace
        # Remove any prose lines that don't look like SQL
        lines = text.strip().splitlines()
        sql_lines = []
        for line in lines:
            stripped = line.strip()
            # Stop collecting if we hit an explanation line after the query
            if sql_lines and stripped and not stripped.upper().startswith((
                "SELECT", "WITH", "WHERE", "FROM", "JOIN", "GROUP", "ORDER",
                "HAVING", "LIMIT", "UNION", "AND", "OR", "ON", "--", "(",
            )) and ";" in "".join(sql_lines):
                break
            sql_lines.append(line)

        return "\n".join(sql_lines).strip()
