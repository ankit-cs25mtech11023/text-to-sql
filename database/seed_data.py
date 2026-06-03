"""
Generates synthetic GST data and populates gst_demo.db.
Run: python database/seed_data.py
"""
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

from faker import Faker

fake = Faker("en_IN")
random.seed(42)
Faker.seed(42)

DB_PATH = Path(__file__).parent / "gst_demo.db"
SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# ── Reference data ────────────────────────────────────────────────────────────

STATES = [
    ("07", "Delhi", "UT"),
    ("19", "West Bengal", "State"),
    ("27", "Maharashtra", "State"),
    ("29", "Karnataka", "State"),
    ("32", "Kerala", "State"),
    ("33", "Tamil Nadu", "State"),
    ("36", "Telangana", "State"),
    ("08", "Rajasthan", "State"),
    ("09", "Uttar Pradesh", "State"),
    ("24", "Gujarat", "State"),
]

STATE_CODES = [s[0] for s in STATES]
STATE_BY_CODE = {s[0]: s[1] for s in STATES}

# HSN codes: (code, description, chapter, default_tax_rate)
HSN_DATA = [
    ("8471", "Computers and peripherals", "84", 18.0),
    ("8517", "Telephone sets and smartphones", "85", 18.0),
    ("6109", "T-shirts and vests, knitted", "61", 12.0),
    ("6203", "Men's suits, jackets and trousers", "62", 12.0),
    ("8703", "Motor cars", "87", 28.0),
    ("2202", "Aerated waters and soft drinks", "22", 28.0),
    ("0402", "Milk powder and dairy products", "04", 5.0),
    ("1006", "Rice", "10", 0.0),
    ("1001", "Wheat and meslin", "10", 0.0),
    ("3004", "Medicaments (pharma)", "30", 12.0),
    ("9403", "Furniture and parts", "94", 18.0),
    ("7308", "Structures of iron or steel", "73", 18.0),
    ("3923", "Plastic articles for packaging", "39", 18.0),
    ("8443", "Printing machinery", "84", 18.0),
    ("9619", "Sanitary towels and diapers", "96", 12.0),
    ("2710", "Petroleum oils", "27", 0.0),
    ("8544", "Insulated wire and cables", "85", 28.0),
    ("4901", "Printed books", "49", 0.0),
    ("6402", "Footwear with rubber soles", "64", 18.0),
    ("1513", "Coconut oil", "15", 5.0),
]

PORT_CODES = ["INMAA1", "INBOM4", "INDEL4", "INCCU1", "INKOC1"]

UNITS = ["KGS", "NOS", "MTR", "LTR", "SQM", "PCS", "BOX", "SET"]

TAX_RATES = [0.0, 5.0, 12.0, 18.0, 28.0]

INVOICE_TYPES = ["B2B", "B2CL", "B2CS", "EXPORT", "CDNR"]

RETURN_PERIODS = [
    f"{m:02d}2025" for m in range(4, 13)
] + [
    f"{m:02d}2026" for m in range(1, 4)
]  # Apr 2025 – Mar 2026 (12 months)


# ── Helpers ───────────────────────────────────────────────────────────────────

def random_gstin(state_code: str) -> str:
    pan = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ", k=5)) + \
          "".join(random.choices("0123456789", k=4)) + \
          random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    return f"{state_code}{pan}1Z5"


def random_date_in_period(return_period: str) -> date:
    month = int(return_period[:2])
    year = int(return_period[2:])
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        end = date(year, month + 1, 1) - timedelta(days=1)
    delta = (end - start).days
    return start + timedelta(days=random.randint(0, delta))


def compute_tax(taxable_value: float, tax_rate: float, is_intra: bool) -> tuple[float, float, float]:
    total_tax = round(taxable_value * tax_rate / 100, 2)
    if is_intra:
        half = round(total_tax / 2, 2)
        return half, half, 0.0
    else:
        return 0.0, 0.0, total_tax


def is_intra_state(supplier_state: str, place_of_supply: str) -> bool:
    return supplier_state == place_of_supply


# ── Seed functions ────────────────────────────────────────────────────────────

def seed_state_codes(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO state_codes VALUES (?, ?, ?)",
        STATES,
    )


def seed_hsn_master(conn: sqlite3.Connection) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO hsn_master VALUES (?, ?, ?, ?)",
        HSN_DATA,
    )


def seed_suppliers(conn: sqlite3.Connection, n: int = 50) -> list[dict]:
    suppliers = []
    used_gstins: set[str] = set()
    states_cycle = STATES * ((n // len(STATES)) + 1)

    for i, (state_code, state_name, _) in enumerate(states_cycle[:n]):
        gstin = random_gstin(state_code)
        while gstin in used_gstins:
            gstin = random_gstin(state_code)
        used_gstins.add(gstin)

        reg_type = random.choices(["Regular", "Composition"], weights=[90, 10])[0]
        created = fake.date_between(start_date=date(2018, 7, 1), end_date=date(2024, 12, 31))

        suppliers.append({
            "supplier_id": i + 1,
            "gstin": gstin,
            "legal_name": fake.company(),
            "trade_name": fake.company() if random.random() > 0.4 else None,
            "state_code": state_code,
            "state_name": state_name,
            "registration_type": reg_type,
            "created_at": str(created),
        })

    conn.executemany(
        """INSERT INTO suppliers
           (supplier_id, gstin, legal_name, trade_name, state_code, state_name, registration_type, created_at)
           VALUES (:supplier_id, :gstin, :legal_name, :trade_name, :state_code, :state_name, :registration_type, :created_at)""",
        suppliers,
    )
    return suppliers


def seed_buyers(conn: sqlite3.Connection, n: int = 200) -> list[dict]:
    buyers = []
    type_weights = [50, 15, 25, 10]  # B2B, B2CL, B2CS, EXPORT
    buyer_types = random.choices(INVOICE_TYPES[:4], weights=type_weights, k=n)

    for i, btype in enumerate(buyer_types):
        state_code, state_name, _ = random.choice(STATES)
        is_registered = btype == "B2B"

        buyers.append({
            "buyer_id": i + 1,
            "gstin": random_gstin(state_code) if is_registered else None,
            "legal_name": fake.company() if is_registered else (fake.name() if btype != "B2CS" else None),
            "state_code": state_code,
            "state_name": state_name,
            "buyer_type": btype,
        })

    conn.executemany(
        """INSERT INTO buyers
           (buyer_id, gstin, legal_name, state_code, state_name, buyer_type)
           VALUES (:buyer_id, :gstin, :legal_name, :state_code, :state_name, :buyer_type)""",
        buyers,
    )
    return buyers


def seed_invoices(
    conn: sqlite3.Connection,
    suppliers: list[dict],
    buyers: list[dict],
    n_invoices: int = 5000,
    n_items_target: int = 15000,
) -> None:
    b2b_buyers = [b for b in buyers if b["buyer_type"] == "B2B"]
    b2cl_buyers = [b for b in buyers if b["buyer_type"] == "B2CL"]
    b2cs_buyers = [b for b in buyers if b["buyer_type"] == "B2CS"]
    export_buyers = [b for b in buyers if b["buyer_type"] == "EXPORT"]

    invoices = []
    items = []
    export_rows = []

    avg_items = n_items_target // n_invoices

    for inv_idx in range(n_invoices):
        supplier = random.choice(suppliers)
        return_period = random.choice(RETURN_PERIODS)
        inv_date = random_date_in_period(return_period)

        # Pick invoice type based on weights
        inv_type = random.choices(
            ["B2B", "B2CL", "B2CS", "EXPORT", "CDNR"],
            weights=[45, 10, 25, 10, 10],
        )[0]

        # Select buyer
        if inv_type == "B2B" and b2b_buyers:
            buyer = random.choice(b2b_buyers)
        elif inv_type == "B2CL" and b2cl_buyers:
            buyer = random.choice(b2cl_buyers)
        elif inv_type == "B2CS":
            buyer = random.choice(b2cs_buyers) if b2cs_buyers else None
        elif inv_type == "EXPORT" and export_buyers:
            buyer = random.choice(export_buyers)
        elif inv_type == "CDNR" and b2b_buyers:
            buyer = random.choice(b2b_buyers)
        else:
            buyer = random.choice(buyers)

        buyer_id = buyer["buyer_id"] if (buyer and inv_type != "B2CS") else None

        # Place of supply: 80% intra-state, 20% inter-state; EXPORT always foreign
        if inv_type == "EXPORT":
            place_of_supply = "96"  # overseas / foreign
        elif random.random() < 0.80:
            place_of_supply = supplier["state_code"]
        else:
            place_of_supply = random.choice([s for s in STATE_CODES if s != supplier["state_code"]])

        reverse_charge = random.random() < 0.03  # ~3% have reverse charge

        # Generate line items
        n_items = max(1, round(random.gauss(avg_items, 1)))
        invoice_value = 0.0

        for item_idx in range(n_items):
            hsn_row = random.choice(HSN_DATA)
            hsn_code, hsn_desc, _, default_rate = hsn_row
            tax_rate = default_rate

            quantity = round(random.uniform(1, 100), 2)
            unit = random.choice(UNITS)
            taxable_value = round(random.uniform(500, 50000), 2)

            intra = is_intra_state(supplier["state_code"], place_of_supply)
            cgst, sgst, igst = compute_tax(taxable_value, tax_rate, intra)

            # Cess only on 28% goods with 10% probability
            cess = round(taxable_value * 0.05, 2) if (tax_rate == 28.0 and random.random() < 0.1) else 0.0

            item_total = taxable_value + cgst + sgst + igst + cess
            invoice_value += item_total

            items.append({
                "invoice_id": inv_idx + 1,
                "hsn_code": hsn_code,
                "description": hsn_desc,
                "quantity": quantity,
                "unit": unit,
                "taxable_value": round(taxable_value, 2),
                "tax_rate": tax_rate,
                "cgst_amount": cgst,
                "sgst_amount": sgst,
                "igst_amount": igst,
                "cess_amount": cess,
            })

        invoice_value = round(invoice_value, 2)

        invoices.append({
            "invoice_id": inv_idx + 1,
            "invoice_number": f"INV-{supplier['supplier_id']:03d}-{inv_idx + 1:05d}",
            "invoice_date": str(inv_date),
            "invoice_type": inv_type,
            "supplier_id": supplier["supplier_id"],
            "buyer_id": buyer_id,
            "place_of_supply": place_of_supply,
            "reverse_charge": int(reverse_charge),
            "invoice_value": invoice_value,
            "return_period": return_period,
            "filing_status": random.choices(["Filed", "Pending", "Amended"], weights=[90, 5, 5])[0],
        })

        if inv_type == "EXPORT":
            export_rows.append({
                "invoice_id": inv_idx + 1,
                "port_code": random.choice(PORT_CODES),
                "shipping_bill_no": f"SB{random.randint(1000000, 9999999)}",
                "shipping_bill_date": str(inv_date + timedelta(days=random.randint(1, 7))),
                "export_type": random.choice(["WITH_PAYMENT", "WITHOUT_PAYMENT"]),
            })

    conn.executemany(
        """INSERT INTO invoices
           (invoice_id, invoice_number, invoice_date, invoice_type, supplier_id, buyer_id,
            place_of_supply, reverse_charge, invoice_value, return_period, filing_status)
           VALUES (:invoice_id, :invoice_number, :invoice_date, :invoice_type, :supplier_id,
                   :buyer_id, :place_of_supply, :reverse_charge, :invoice_value, :return_period, :filing_status)""",
        invoices,
    )

    conn.executemany(
        """INSERT INTO invoice_items
           (invoice_id, hsn_code, description, quantity, unit, taxable_value, tax_rate,
            cgst_amount, sgst_amount, igst_amount, cess_amount)
           VALUES (:invoice_id, :hsn_code, :description, :quantity, :unit, :taxable_value,
                   :tax_rate, :cgst_amount, :sgst_amount, :igst_amount, :cess_amount)""",
        items,
    )

    conn.executemany(
        """INSERT INTO export_invoices
           (invoice_id, port_code, shipping_bill_no, shipping_bill_date, export_type)
           VALUES (:invoice_id, :port_code, :shipping_bill_no, :shipping_bill_date, :export_type)""",
        export_rows,
    )

    print(f"  Invoices:       {len(invoices)}")
    print(f"  Invoice items:  {len(items)}")
    print(f"  Export records: {len(export_rows)}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Removed existing {DB_PATH.name}")

    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys=ON;")

    print("Creating schema...")
    conn.executescript(SCHEMA_PATH.read_text())

    print("Seeding reference data...")
    seed_state_codes(conn)
    seed_hsn_master(conn)

    print("Seeding suppliers (50)...")
    suppliers = seed_suppliers(conn, n=50)

    print("Seeding buyers (200)...")
    buyers = seed_buyers(conn, n=200)

    print("Seeding invoices + items...")
    seed_invoices(conn, suppliers, buyers, n_invoices=5000, n_items_target=15000)

    conn.commit()
    conn.close()

    print(f"\nDone. Database written to {DB_PATH}")


if __name__ == "__main__":
    main()
