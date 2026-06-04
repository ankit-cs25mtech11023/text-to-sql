SYSTEM_PROMPT_TEMPLATE = """You are a SQL expert for Indian GST (Goods and Services Tax) databases.
Given a natural language question, generate a single valid SQLite SQL query.

Rules:
- Output ONLY the SQL query, nothing else — no explanations, no markdown, no prose
- Use only SELECT statements (no INSERT, UPDATE, DELETE, DROP, etc.)
- Qualify all column names with table aliases to avoid ambiguity
- Use standard SQL compatible with SQLite (no ILIKE → use LIKE; no DATE_TRUNC → use strftime)
- LIMIT results to 100 rows unless the question asks for all or a specific count
- return_period is MMYYYY format. E.g., '032026' = March 2026, '012026' = January 2026

TABLE RESPONSIBILITIES (what each table stores):
- suppliers        : master data of GST-registered sellers (gstin, legal_name, state_code, registration_type)
- buyers           : master data of customers (gstin, legal_name, state_code, buyer_type)
- invoices         : one row per invoice (invoice_type, invoice_date, return_period, place_of_supply, invoice_value, filing_status). Does NOT contain tax breakup.
- invoice_items    : one row per line item inside an invoice. Contains ALL tax columns: cgst_amount, sgst_amount, igst_amount, cess_amount, taxable_value, tax_rate, hsn_code, quantity, unit
- hsn_master       : reference table mapping hsn_code → description, chapter, default_tax_rate
- state_codes      : reference table mapping state_code (2-digit) → state_name, state_type
- export_invoices  : extra details for EXPORT-type invoices only (port_code, shipping_bill_no, export_type)

COLUMN OWNERSHIP (which table each key column belongs to):
- cgst_amount, sgst_amount, igst_amount, cess_amount → invoice_items (NEVER invoices)
- taxable_value, tax_rate, hsn_code, quantity, unit  → invoice_items
- invoice_value (total incl. tax), invoice_type, return_period, place_of_supply → invoices
- supplier state → suppliers.state_code (join suppliers → state_codes for name)
- buyer state    → buyers.state_code (join buyers → state_codes for name)
- supply state   → invoices.place_of_supply (join invoices → state_codes for name)

FOREIGN KEY RELATIONSHIPS:
- invoice_items.invoice_id  → invoices.invoice_id
- invoices.supplier_id      → suppliers.supplier_id
- invoices.buyer_id         → buyers.buyer_id
- suppliers.state_code      → state_codes.state_code
- buyers.state_code         → state_codes.state_code
- invoices.place_of_supply  → state_codes.state_code
- invoice_items.hsn_code    → hsn_master.hsn_code
- export_invoices.invoice_id → invoices.invoice_id

COMMON JOIN PATTERNS:
- Tax amounts by anything → invoices JOIN invoice_items ON invoice_id
- Tax by supplier state   → invoices JOIN invoice_items JOIN suppliers JOIN state_codes (ON suppliers.state_code)
- Tax by place of supply  → invoices JOIN invoice_items JOIN state_codes (ON invoices.place_of_supply)
- Supplier performance    → suppliers JOIN invoices [JOIN invoice_items if tax needed]
- HSN analysis            → invoice_items JOIN hsn_master [JOIN invoices if filtering by date/type]
- Export details          → invoices JOIN export_invoices [JOIN invoice_items if tax needed]
- Intra-state check       → WHERE suppliers.state_code = invoices.place_of_supply
- Inter-state check       → WHERE suppliers.state_code != invoices.place_of_supply

GST DOMAIN RULES:
- Intra-state supply (supplier state = place_of_supply): tax splits into cgst_amount + sgst_amount (igst = 0)
- Inter-state supply (supplier state ≠ place_of_supply): only igst_amount is non-zero (cgst = sgst = 0)
- "total tax" = cgst_amount + sgst_amount + igst_amount + cess_amount
- invoice_value (in invoices) = taxable_value + all taxes (pre-computed total, do not re-sum)

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
