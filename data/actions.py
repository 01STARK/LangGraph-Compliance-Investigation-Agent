"""
Mock downstream side effects for analyst decisions.
In production these would call real APIs, databases, and notification services.
Each function writes to local files so the demo feels tangible.
"""
import json
from datetime import datetime
from pathlib import Path

DATA_DIR  = Path(__file__).parent
AUDIT_LOG = DATA_DIR / "audit_log.json"
CASES_DIR = DATA_DIR / "cases"
SAR_DIR   = DATA_DIR / "sar_queue"


# ── Audit log ──────────────────────────────────────────────────────────────────

def read_audit_log() -> list[dict]:
    if AUDIT_LOG.exists():
        try:
            return json.loads(AUDIT_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
    return []


def log_decision(
    tx_id: str,
    customer_name: str,
    decision: str,
    risk_score: float,
    risk_level: str,
    analyst: str = "demo_analyst",
) -> dict:
    """Append a decision record to the shared audit log."""
    records = read_audit_log()
    entry = {
        "timestamp":     datetime.utcnow().isoformat(timespec="seconds"),
        "tx_id":         tx_id,
        "customer_name": customer_name,
        "risk_score":    risk_score,
        "risk_level":    risk_level,
        "decision":      decision,
        "analyst":       analyst,
    }
    records.append(entry)
    AUDIT_LOG.write_text(json.dumps(records, indent=2), encoding="utf-8")
    return entry


# ── Case file (escalation) ─────────────────────────────────────────────────────

def create_case(
    tx_id: str,
    customer_name: str,
    risk_score: float,
    report: str,
) -> Path:
    """
    Creates a JSON case file that a senior analyst would pick up.
    Simulates: ticket created in case management system + email sent.
    """
    CASES_DIR.mkdir(exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    case_id   = f"CASE-{tx_id}-{ts}"
    case_file = CASES_DIR / f"{case_id}.json"
    case_data = {
        "case_id":       case_id,
        "created_at":    datetime.utcnow().isoformat(timespec="seconds"),
        "tx_id":         tx_id,
        "customer_name": customer_name,
        "risk_score":    risk_score,
        "status":        "open",
        "assigned_to":   "senior_analyst@bank.com",
        "report":        report,
        "notes":         [],
        # Mock: what a real system would also do
        "_mock_actions": [
            "Email sent to senior_analyst@bank.com",
            "Ticket created in Case Management System",
            "Transaction placed on 24-hour hold",
        ],
    }
    case_file.write_text(json.dumps(case_data, indent=2), encoding="utf-8")
    return case_file


# ── SAR queue ──────────────────────────────────────────────────────────────────

def queue_sar(
    tx_id: str,
    customer_name: str,
    risk_score: float,
    sar_text: str,
) -> Path:
    """
    Writes a SAR file to the queue directory.
    Simulates: SAR submitted to FinCEN BSA E-Filing system + account flagged.
    """
    SAR_DIR.mkdir(exist_ok=True)
    ts     = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    sar_id = f"SAR-{tx_id}-{ts}"
    sar_file = SAR_DIR / f"{sar_id}.json"
    sar_data = {
        "sar_id":            sar_id,
        "filed_at":          datetime.utcnow().isoformat(timespec="seconds"),
        "status":            "queued",
        "fincen_submission": "pending_review",
        "tx_id":             tx_id,
        "customer_name":     customer_name,
        "risk_score":        risk_score,
        "narrative":         sar_text,
        # Mock: what a real system would also do
        "_mock_actions": [
            "SAR queued in FinCEN BSA E-Filing system",
            "Account flagged for enhanced monitoring",
            "Compliance officer notified via secure message",
            "30-day SAR filing deadline timer started",
            "Tipping-off restriction applied to account",
        ],
    }
    sar_file.write_text(json.dumps(sar_data, indent=2), encoding="utf-8")
    return sar_file
