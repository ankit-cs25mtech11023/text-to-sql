CREATE TABLE IF NOT EXISTS state_codes (
    state_code          TEXT PRIMARY KEY,
    state_name          TEXT NOT NULL,
    state_type          TEXT                        -- 'State', 'UT'
);

CREATE TABLE IF NOT EXISTS hsn_master (
    hsn_code            TEXT PRIMARY KEY,
    description         TEXT NOT NULL,
    chapter             TEXT,
    default_tax_rate    REAL
);

CREATE TABLE IF NOT EXISTS suppliers (
    supplier_id         INTEGER PRIMARY KEY,
    gstin               TEXT NOT NULL UNIQUE,
    legal_name          TEXT NOT NULL,
    trade_name          TEXT,
    state_code          TEXT NOT NULL,
    state_name          TEXT NOT NULL,
    registration_type   TEXT DEFAULT 'Regular',
    created_at          DATE NOT NULL,
    FOREIGN KEY (state_code) REFERENCES state_codes(state_code)
);

CREATE TABLE IF NOT EXISTS buyers (
    buyer_id            INTEGER PRIMARY KEY,
    gstin               TEXT,
    legal_name          TEXT,
    state_code          TEXT NOT NULL,
    state_name          TEXT NOT NULL,
    buyer_type          TEXT NOT NULL               -- 'B2B', 'B2CL', 'B2CS', 'EXPORT'
);

CREATE TABLE IF NOT EXISTS invoices (
    invoice_id          INTEGER PRIMARY KEY,
    invoice_number      TEXT NOT NULL,
    invoice_date        DATE NOT NULL,
    invoice_type        TEXT NOT NULL,              -- 'B2B', 'B2CL', 'B2CS', 'EXPORT', 'CDNR', 'CDNUR'
    supplier_id         INTEGER NOT NULL,
    buyer_id            INTEGER,
    place_of_supply     TEXT NOT NULL,
    reverse_charge      BOOLEAN DEFAULT FALSE,
    invoice_value       REAL NOT NULL,
    return_period       TEXT NOT NULL,              -- MMYYYY format e.g. '032026'
    filing_status       TEXT DEFAULT 'Filed',
    FOREIGN KEY (supplier_id) REFERENCES suppliers(supplier_id),
    FOREIGN KEY (buyer_id) REFERENCES buyers(buyer_id)
);

CREATE TABLE IF NOT EXISTS invoice_items (
    item_id             INTEGER PRIMARY KEY,
    invoice_id          INTEGER NOT NULL,
    hsn_code            TEXT NOT NULL,
    description         TEXT,
    quantity            REAL,
    unit                TEXT,
    taxable_value       REAL NOT NULL,
    tax_rate            REAL NOT NULL,              -- 0, 5, 12, 18, 28
    cgst_amount         REAL DEFAULT 0,
    sgst_amount         REAL DEFAULT 0,
    igst_amount         REAL DEFAULT 0,
    cess_amount         REAL DEFAULT 0,
    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
);

CREATE TABLE IF NOT EXISTS export_invoices (
    export_id           INTEGER PRIMARY KEY,
    invoice_id          INTEGER NOT NULL,
    port_code           TEXT,
    shipping_bill_no    TEXT,
    shipping_bill_date  DATE,
    export_type         TEXT NOT NULL,              -- 'WITH_PAYMENT', 'WITHOUT_PAYMENT'
    FOREIGN KEY (invoice_id) REFERENCES invoices(invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_invoices_supplier ON invoices(supplier_id);
CREATE INDEX IF NOT EXISTS idx_invoices_return_period ON invoices(return_period);
CREATE INDEX IF NOT EXISTS idx_invoices_type ON invoices(invoice_type);
CREATE INDEX IF NOT EXISTS idx_invoice_items_invoice ON invoice_items(invoice_id);
CREATE INDEX IF NOT EXISTS idx_invoice_items_hsn ON invoice_items(hsn_code);
