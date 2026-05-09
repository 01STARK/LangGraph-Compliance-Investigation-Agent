import sqlite3
import sys
from pathlib import Path
from datetime import datetime, timedelta

DB_PATH = Path(__file__).parent.parent / "data" / "compliance.db"

# Allow importing sanctions_list from the data package regardless of cwd
sys.path.insert(0, str(Path(__file__).parent.parent))
from data.sanctions_list import SANCTIONED_ENTITIES


def get_customer_info(customer_id: str) -> dict:
    if not DB_PATH.exists():
        return {}
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,))
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else {}


def get_customer_history(customer_id: str, limit: int = 30) -> list[dict]:
    if not DB_PATH.exists():
        return []
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.execute(
        """
        SELECT * FROM transactions
        WHERE customer_id = ?
        ORDER BY timestamp DESC
        LIMIT ?
        """,
        (customer_id, limit),
    )
    rows = [dict(r) for r in cur.fetchall()]
    conn.close()
    return rows


def compute_velocity(history: list[dict]) -> dict:
    if not history:
        return {
            "tx_count_7d": 0,
            "total_7d": 0.0,
            "avg_amount": 0.0,
            "max_amount": 0.0,
            "structuring_flag": False,
            "cross_border_count": 0,
        }

    cutoff = datetime.utcnow() - timedelta(days=7)
    recent = []
    for t in history:
        try:
            if datetime.fromisoformat(t["timestamp"]) > cutoff:
                recent.append(t)
        except (ValueError, TypeError):
            pass

    amounts = [t["amount"] for t in history]
    return {
        "tx_count_7d": len(recent),
        "total_7d": round(sum(t["amount"] for t in recent), 2),
        "avg_amount": round(sum(amounts) / len(amounts), 2),
        "max_amount": max(amounts),
        # Classic structuring: multiple txns just under $10 k CTR threshold
        "structuring_flag": any(9000 <= t["amount"] < 10000 for t in history),
        "cross_border_count": sum(1 for t in history if t.get("cross_border")),
    }


def check_sanctions(name: str, country: str = "") -> dict:
    """Fuzzy-match name against the fictional sanctions list."""
    name_lower = name.lower().strip()
    for entity in SANCTIONED_ENTITIES:
        entity_name_lower = entity["name"].lower()
        if entity_name_lower in name_lower or name_lower in entity_name_lower:
            return {
                "match": True,
                "matched_entity": entity["name"],
                "country": entity["country"],
                "reason": entity["reason"],
                "list": entity["list"],
            }
    return {"match": False}
