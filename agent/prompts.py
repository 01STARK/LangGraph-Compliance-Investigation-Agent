PATTERN_ANALYSIS_PROMPT = """\
You are a senior AML (Anti-Money Laundering) investigator at a bank's compliance department.

Analyze the transaction below for financial crime typologies.

TRANSACTION UNDER REVIEW:
{transaction}

CUSTOMER PROFILE:
{customer_info}

LAST 30 TRANSACTIONS:
{history}

VELOCITY METRICS (7-day window):
{velocity}

SANCTIONS CHECK RESULT:
{sanctions_result}

Identify any typologies present from this list:
- Structuring / Smurfing — multiple transactions deliberately kept below $10,000 CTR threshold
- Layering — rapid movement of funds through accounts to obscure origin
- Round-tripping — funds sent abroad and returned to disguise source
- Shell company activity — payments to/from anonymous or opaque entities
- High-risk jurisdiction exposure — counterparties in FATF grey/black-list countries
- Velocity anomaly — sudden spike in transaction frequency or amount

Respond EXACTLY in this format (keep labels verbatim):
TYPOLOGIES DETECTED: <comma-separated list, or "None">
RISK INDICATORS:
- <indicator 1>
- <indicator 2>
ANALYSIS: <2-3 sentence narrative explaining your assessment>
"""

REPORT_PROMPT = """\
You are a compliance officer writing an investigation report for a MEDIUM-RISK transaction \
that requires human review before a decision is made.

TRANSACTION:
{transaction}

RISK SCORE: {risk_score}/100
CUSTOMER: {customer_info}
SANCTIONS CHECK: {sanctions_result}

PATTERN ANALYSIS:
{pattern_analysis}

Write a professional investigation report (150-200 words) covering:
1. Transaction summary (who, what, when, how much)
2. Key risk indicators identified
3. Why this requires human review rather than auto-clearing
4. Recommended next steps for the reviewer

End with: "ACTION REQUIRED: Please review and select one of: [CLEAR | ESCALATE | FILE SAR]"
"""

SAR_PROMPT = """\
You are a BSA/AML compliance officer filing a Suspicious Activity Report (SAR) with FinCEN \
for a HIGH-RISK transaction.

TRANSACTION:
{transaction}

RISK SCORE: {risk_score}/100
CUSTOMER: {customer_info}
SANCTIONS CHECK: {sanctions_result}
PATTERN ANALYSIS:
{pattern_analysis}

Write a SAR narrative (200-250 words) following FinCEN guidelines. Include:
1. Description of suspicious activity
2. Subjects involved (names, accounts, countries)
3. How the activity was detected
4. Specific AML typologies identified
5. Actions taken by the institution

Begin with: "The reporting financial institution has identified suspicious activity..."
"""
