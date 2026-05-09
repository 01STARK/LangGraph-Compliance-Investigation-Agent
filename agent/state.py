from typing import TypedDict, Annotated, Optional
import operator


class InvestigationState(TypedDict):
    # Input
    transaction: dict

    # Step findings
    customer_info: dict
    customer_history: list
    velocity_metrics: dict
    sanctions_result: dict
    pattern_analysis: str

    # Risk assessment
    risk_score: float
    risk_level: str          # "low" | "medium" | "high"

    # Output
    decision: str            # "cleared" | "escalated" | "sar_filed"
    report: str
    sar_text: str

    # Control
    sanctions_retries: int
    error: Optional[str]

    # Audit trail — each node appends, never overwrites
    step_log: Annotated[list, operator.add]
