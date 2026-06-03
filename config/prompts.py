SYSTEM_PROMPT_TEMPLATE = """You are a SQL expert for Indian GST (Goods and Services Tax) databases.
Given a natural language question, generate a single valid SQLite SQL query.

Rules:
- Output ONLY the SQL query, nothing else — no explanations, no markdown, no prose
- Use only SELECT statements (no INSERT, UPDATE, DELETE, DROP, etc.)
- For intra-state supplies: tax = cgst_amount + sgst_amount. For inter-state: tax = igst_amount
- "total tax" means cgst_amount + sgst_amount + igst_amount + cess_amount
- return_period is MMYYYY format. E.g., '032026' = March 2026, '012026' = January 2026
- Qualify ambiguous column names with table aliases
- Use standard SQL compatible with SQLite (no ILIKE, use LIKE; no DATE_TRUNC, use strftime)
- When asked about a state, join with state_codes or suppliers/buyers to get state_name
- LIMIT results to 100 rows unless the question asks for all or a specific count

DATABASE SCHEMA:
{ddl}

COLUMN DESCRIPTIONS:
{descriptions}

SAMPLE DATA (first 3 rows per table):
{sample_rows}
{few_shot_block}"""

USER_PROMPT_TEMPLATE = "Question: {question}"

CORRECTION_PROMPT_TEMPLATE = """The SQL query you generated has an error.

Original question: {question}

Your SQL:
{sql}

Error: {error}

Fix the SQL query. Output ONLY the corrected SQL, nothing else."""

FEW_SHOT_HEADER = "\nEXAMPLE QUESTION-SQL PAIRS:\n"

FEW_SHOT_EXAMPLES = [
    {
        "question": "How many invoices were filed in March 2026?",
        "sql": "SELECT COUNT(*) AS invoice_count FROM invoices WHERE return_period = '032026';",
    },
    {
        "question": "What is the total taxable value by invoice type?",
        "sql": (
            "SELECT i.invoice_type, SUM(ii.taxable_value) AS total_taxable_value "
            "FROM invoices i JOIN invoice_items ii ON i.invoice_id = ii.invoice_id "
            "GROUP BY i.invoice_type ORDER BY total_taxable_value DESC;"
        ),
    },
    {
        "question": "List the top 5 suppliers by total invoice value.",
        "sql": (
            "SELECT s.legal_name, SUM(i.invoice_value) AS total_value "
            "FROM suppliers s JOIN invoices i ON s.supplier_id = i.supplier_id "
            "GROUP BY s.supplier_id, s.legal_name "
            "ORDER BY total_value DESC LIMIT 5;"
        ),
    },
    {
        "question": "What is the total IGST collected from inter-state B2B invoices?",
        "sql": (
            "SELECT SUM(ii.igst_amount) AS total_igst "
            "FROM invoices i "
            "JOIN invoice_items ii ON i.invoice_id = ii.invoice_id "
            "JOIN suppliers s ON i.supplier_id = s.supplier_id "
            "WHERE i.invoice_type = 'B2B' AND i.place_of_supply != s.state_code;"
        ),
    },
    {
        "question": "How many export invoices used the WITH_PAYMENT option?",
        "sql": (
            "SELECT COUNT(*) AS count "
            "FROM export_invoices WHERE export_type = 'WITH_PAYMENT';"
        ),
    },
]


def build_few_shot_block(n: int) -> str:
    if n == 0:
        return ""
    examples = FEW_SHOT_EXAMPLES[:n]
    lines = [FEW_SHOT_HEADER]
    for ex in examples:
        lines.append(f"Q: {ex['question']}")
        lines.append(f"SQL: {ex['sql']}\n")
    return "\n".join(lines)
