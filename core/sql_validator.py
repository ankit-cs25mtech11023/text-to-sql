from dataclasses import dataclass

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword, DDL, DML


BLOCKED_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "GRANT", "REVOKE", "PRAGMA", "ATTACH", "DETACH",
}


@dataclass
class ValidationResult:
    valid: bool
    error: str | None = None


def validate_sql(sql: str, allowed_tables: set[str] | None = None) -> ValidationResult:
    if not sql or not sql.strip():
        return ValidationResult(valid=False, error="Empty SQL query.")

    statements = sqlparse.parse(sql.strip())

    if len(statements) > 1 or (len(statements) == 1 and _has_multiple_statements(statements[0])):
        return ValidationResult(valid=False, error="Only a single SQL statement is allowed.")

    stmt = statements[0]

    # First meaningful token must be SELECT or WITH (CTE)
    first_keyword = _first_keyword(stmt)
    if first_keyword not in ("SELECT", "WITH"):
        return ValidationResult(
            valid=False,
            error=f"Only SELECT queries are allowed. Got: {first_keyword or 'unknown'}.",
        )

    # Blocklist check across all tokens
    for token in stmt.flatten():
        if token.ttype in (Keyword, DDL, DML):
            val = token.normalized.upper()
            if val in BLOCKED_KEYWORDS:
                return ValidationResult(
                    valid=False,
                    error=f"Forbidden keyword in query: {val}.",
                )

    if allowed_tables:
        referenced = _extract_table_names(stmt)
        unknown = referenced - allowed_tables
        if unknown:
            return ValidationResult(
                valid=False,
                error=f"Query references unknown tables: {', '.join(sorted(unknown))}.",
            )

    return ValidationResult(valid=True)


def _first_keyword(stmt: Statement) -> str | None:
    for token in stmt.tokens:
        if token.ttype in (Keyword, DDL, DML):
            return token.normalized.upper()
        if not token.is_whitespace:
            # Could be a grouped token — check its first real token
            flat = list(token.flatten())
            for t in flat:
                if t.ttype in (Keyword, DDL, DML):
                    return t.normalized.upper()
    return None


def _has_multiple_statements(stmt: Statement) -> bool:
    # sqlparse.parse splits on semicolons; a trailing semicolon is fine
    # but mid-query semicolons indicate injection
    semicolons = [t for t in stmt.flatten() if t.ttype is sqlparse.tokens.Punctuation and t.value == ";"]
    if len(semicolons) > 1:
        return True
    if len(semicolons) == 1:
        # semicolon must be the last non-whitespace token
        tokens = [t for t in stmt.flatten() if not t.is_whitespace]
        return tokens[-1].value != ";"
    return False


def _extract_table_names(stmt: Statement) -> set[str]:
    from sqlparse.sql import Identifier, IdentifierList
    from sqlparse.tokens import Keyword

    tables: set[str] = set()
    from_seen = False

    for token in stmt.flatten():
        if token.ttype is Keyword and token.normalized.upper() in ("FROM", "JOIN", "INNER JOIN", "LEFT JOIN"):
            from_seen = True
        elif from_seen:
            if token.ttype is sqlparse.tokens.Name:
                tables.add(token.value.lower())
                from_seen = False
            elif token.ttype not in (sqlparse.tokens.Whitespace, sqlparse.tokens.Newline):
                from_seen = False

    return tables
