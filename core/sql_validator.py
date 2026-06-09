from dataclasses import dataclass

import sqlparse
from sqlparse.sql import Statement
from sqlparse.tokens import Keyword


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

    # Statement must resolve to SELECT. get_type() sees through CTEs:
    # 'WITH x AS (...) SELECT ...' -> 'SELECT', but 'WITH x AS (...) DELETE ...' -> 'DELETE'.
    stmt_type = stmt.get_type()
    if stmt_type != "SELECT":
        return ValidationResult(
            valid=False,
            error=f"Only SELECT queries are allowed. Got: {stmt_type}.",
        )

    # Blocklist check across all tokens (ttype in Keyword matches all subtypes:
    # Keyword.DML, Keyword.DDL, Keyword.CTE, etc.) — defense in depth.
    for token in stmt.flatten():
        if token.ttype is not None and token.ttype in Keyword:
            val = token.normalized.upper()
            if val in BLOCKED_KEYWORDS:
                return ValidationResult(
                    valid=False,
                    error=f"Forbidden keyword in query: {val}.",
                )

    if allowed_tables:
        referenced = _extract_table_names(stmt)
        # CTE names are defined locally in the query, not real tables — exclude them.
        unknown = referenced - allowed_tables - _cte_names(stmt)
        if unknown:
            return ValidationResult(
                valid=False,
                error=f"Query references unknown tables: {', '.join(sorted(unknown))}.",
            )

    return ValidationResult(valid=True)


def _cte_names(stmt: Statement) -> set[str]:
    """Names defined as CTEs: the '<name>' in 'WITH <name> AS ( ... )'. A CTE
    definition is the only place a Name immediately precedes 'AS (' — table and
    column aliases place the name AFTER AS."""
    Name = sqlparse.tokens.Name
    Punctuation = sqlparse.tokens.Punctuation

    names: set[str] = set()
    toks = [t for t in stmt.flatten() if not t.is_whitespace]
    for i, t in enumerate(toks):
        if t.ttype is Name and i + 2 < len(toks):
            nxt, after = toks[i + 1], toks[i + 2]
            if (
                nxt.ttype is Keyword
                and nxt.normalized.upper() == "AS"
                and after.ttype is Punctuation
                and after.value == "("
            ):
                names.add(t.value.lower())
    return names


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


_JOIN_KEYWORDS = {
    "FROM", "JOIN", "INNER JOIN", "LEFT JOIN", "RIGHT JOIN",
    "FULL JOIN", "CROSS JOIN", "LEFT OUTER JOIN", "RIGHT OUTER JOIN",
    "FULL OUTER JOIN",
}


def _extract_table_names(stmt: Statement) -> set[str]:
    """Extract referenced table names, including schema-qualified dotted names
    (e.g. 'public.tbl_x', 'live_reports.r3b_...'). After a FROM/JOIN keyword we
    accumulate a Name (Punctuation '.' Name)* sequence into a single dotted
    identifier, then stop at the first non-identifier token (alias, '(', etc.)."""
    Name = sqlparse.tokens.Name
    Punctuation = sqlparse.tokens.Punctuation

    tables: set[str] = set()
    expecting = False        # just saw FROM/JOIN — next identifier is a table
    current: list[str] = []  # building a dotted identifier

    def flush() -> None:
        nonlocal current, expecting
        if current:
            tables.add("".join(current).lower())
        current = []
        expecting = False

    for token in stmt.flatten():
        if token.is_whitespace:
            if expecting and current:
                flush()
            continue
        if token.ttype is Keyword and token.normalized.upper() in _JOIN_KEYWORDS:
            flush()
            expecting = True
            continue
        if expecting:
            if token.ttype is Name:
                current.append(token.value)
            elif token.ttype is Punctuation and token.value == ".":
                current.append(".")
            else:
                flush()

    if expecting and current:
        flush()
    return tables
