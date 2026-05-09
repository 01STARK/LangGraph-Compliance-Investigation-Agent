"""
Run once to create and populate the SQLite compliance database.
Usage: python data/seed_data.py
"""
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta
import random

DB_PATH = Path(__file__).parent / "compliance.db"


def create_tables(conn: sqlite3.Connection) -> None:
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS customers (
            id          TEXT PRIMARY KEY,
            name        TEXT NOT NULL,
            email       TEXT,
            country     TEXT,
            account_age_days INTEGER,
            risk_tier   TEXT DEFAULT 'standard'
        );

        CREATE TABLE IF NOT EXISTS transactions (
            id              TEXT PRIMARY KEY,
            customer_id     TEXT NOT NULL,
            amount          REAL NOT NULL,
            currency        TEXT DEFAULT 'USD',
            type            TEXT,
            recipient_name  TEXT,
            recipient_country TEXT,
            timestamp       TEXT NOT NULL,
            cross_border    INTEGER DEFAULT 0,
            FOREIGN KEY(customer_id) REFERENCES customers(id)
        );
    """)
    conn.commit()


def seed(conn: sqlite3.Connection) -> None:
    now = datetime.utcnow()

    def ts(days_ago: float, hours_ago: float = 0) -> str:
        return (now - timedelta(days=days_ago, hours=hours_ago)).isoformat()

    def tx_id(n: int) -> str:
        return f"TXN{n:06d}"

    # ── Customers ─────────────────────────────────────────────────────────────
    customers = [
        # c001 — long-standing low-risk retail customer
        ("c001", "Alice Johnson", "alice@email.com", "US", 2100, "standard"),
        # c002 — mid-tier customer with some offshore exposure
        ("c002", "Maria Chen", "mchen@corp.com", "US", 720, "standard"),
        # c003 — brand-new account, very suspicious
        ("c003", "James Kowalski", "jk@protonmail.com", "US", 28, "high"),
        # c004 — layering pattern, mid-tenure
        ("c004", "Alex Rodriguez", "alex.r@fastmail.com", "US", 185, "high"),
        # c005 — normal business customer
        ("c005", "Bright Star LLC", "billing@brightstar.com", "US", 900, "standard"),
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO customers VALUES (?,?,?,?,?,?)", customers
    )

    # ── Transactions ───────────────────────────────────────────────────────────
    rows = []
    n = 1

    # c001 — Alice: small, regular, domestic payments — clearly clean
    for i in range(24):
        rows.append((
            tx_id(n), "c001", round(random.uniform(50, 800), 2), "USD",
            random.choice(["ACH", "Debit", "Check"]),
            random.choice(["Amazon", "Whole Foods", "AT&T", "Netflix", "Landlord LLC"]),
            "US", ts(random.uniform(0, 365)), 0
        ))
        n += 1

    # c002 — Maria: mostly normal but one large offshore wire — medium risk
    for i in range(18):
        rows.append((
            tx_id(n), "c002", round(random.uniform(200, 3000), 2), "USD",
            "ACH", random.choice(["City Power", "Safeway", "Chase Mortgage", "Verizon"]),
            "US", ts(random.uniform(5, 300)), 0
        ))
        n += 1
    # The suspicious one — large wire to offshore LLC
    rows.append((
        tx_id(n), "c002", 8500.00, "USD", "Wire",
        "Unknown Offshore LLC", "Cayman Islands", ts(1), 1
    ))
    n += 1

    # c003 — James: new account, classic structuring pattern (multiple ~$9,800 txns)
    for i in range(4):
        rows.append((
            tx_id(n), "c003", 9800.00 - (i * 50), "USD", "Wire",
            "Sunrise Financial SA", "Panama", ts(i * 2), 1
        ))
        n += 1
    rows.append((
        tx_id(n), "c003", 9750.00, "USD", "Wire",
        "Sunrise Financial SA", "Panama", ts(9), 1
    ))
    n += 1

    # c004 — Alex: rapid in-out layering pattern
    amounts_in  = [25000, 12000, 8000, 5000]
    amounts_out = [24500, 11800, 7900, 4900]
    for i, (ain, aout) in enumerate(zip(amounts_in, amounts_out)):
        rows.append((
            tx_id(n), "c004", ain, "USD", "Wire",
            "ABC Trading Panama", "Panama", ts(i * 3 + 0.1), 1
        ))
        n += 1
        rows.append((
            tx_id(n), "c004", aout, "USD", "Wire",
            "XYZ Consulting Dubai", "UAE", ts(i * 3 + 0.5), 1
        ))
        n += 1

    # c005 — Bright Star LLC: normal B2B payments
    for i in range(20):
        rows.append((
            tx_id(n), "c005", round(random.uniform(1000, 15000), 2), "USD",
            "Wire", random.choice(["Office Depot Corp", "AWS Services", "Dell Technologies"]),
            "US", ts(random.uniform(0, 180)), 0
        ))
        n += 1

    conn.executemany(
        "INSERT OR REPLACE INTO transactions VALUES (?,?,?,?,?,?,?,?,?)", rows
    )
    conn.commit()
    print(f"Seeded {len(customers)} customers and {len(rows)} transactions -> {DB_PATH}")


if __name__ == "__main__":
    if DB_PATH.exists():
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    create_tables(conn)
    seed(conn)
    conn.close()
