"""Generate demo_suites/v1 (lower quality) and v2 (improved ~40%) fixtures."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent / "demo_suites"

# Shared business domain: DCFO late-fee / payment operations.
DOMAIN = "DCFO late fee and payment operations"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# V1 — lower quality: vague, incomplete, unit-ish noise, thin requirements
# ---------------------------------------------------------------------------

V1_FEATURES = {
    "login.feature": """
Feature: Login stuff
  Scenario: user login
    Given user
    When login
    Then ok
""",
    "dashboard.feature": """
Feature: Dashboard
  Scenario: see dashboard
    When open app
    Then page loads
""",
    "late_fee_basic.feature": """
Feature: Late fee
  Scenario: apply fee
    Given overdue
    When job runs
    Then fee added
""",
    "late_fee_skip.feature": """
Feature: Skip fee
  Scenario: no fee
    Given recent payment due
    When job
    Then nothing
""",
    "waiver.feature": """
Feature: Waiver
  Scenario: waive
    Given admin
    When waive
    Then balance fixed
""",
    "notifications.feature": """
Feature: Notify
  Scenario: send email
    When fee applied
    Then email somehow
""",
    "report.feature": """
Feature: Report
  Scenario: report
    Given data
    When export
    Then csv
""",
    "retry.feature": """
Feature: Retry
  Scenario: retry fail
    Given error
    When retry
    Then maybe works
""",
    "config.feature": """
Feature: Config
  Scenario: load settings
    When start
    Then config loaded
""",
    "audit.feature": """
Feature: Audit
  Scenario: log change
    When fee change
    Then log row
""",
    "search.feature": """
Feature: Search accounts
  Scenario: find account
    Given query
    When search
    Then results
""",
    "unit_validate_helper.feature": """
Feature: Helper validate
  # noise: looks like a unit test, not a business journey
  Scenario: null check
    Given null input
    When validate helper called
    Then returns false
""",
    "misc_ui.feature": """
Feature: Misc UI
  Scenario: button click
    When click button
    Then something happens
""",
}

V1_REQUIREMENTS = {
    "REQ-01-login.md": """
# Login
Users should be able to log in.
- login works
- bad password fails somehow
""",
    "REQ-02-dashboard.md": """
# Dashboard
Show dashboard after login.
""",
    "REQ-03-late-fee.md": """
# Late fee
System applies late fee for overdue.
AC: fee is applied
""",
    "REQ-04-grace.md": """
# Grace
No fee in grace period.
""",
    "REQ-05-waiver.md": """
# Waiver
Admin can waive fees.
""",
    "REQ-06-notify.md": """
# Notifications
Send notifications when fee applied.
""",
    "REQ-07-report.md": """
# Reports
Export report of fees.
""",
    "REQ-08-retry.md": """
# Retry
Retry on failure.
""",
    "REQ-09-config.md": """
# Config
Load configuration at startup.
""",
    "REQ-10-audit.md": """
# Audit
Keep audit of changes.
""",
    "REQ-11-search.md": """
# Search
Search for accounts.
""",
    "REQ-12-validate.md": """
# Validation
Validate inputs.
""",
    "REQ-13-ui.md": """
# UI
UI should work.
""",
}


# ---------------------------------------------------------------------------
# V2 — improved ~40%: clearer BDD, journey focus, richer requirement sections
# ---------------------------------------------------------------------------

V2_FEATURES = {
    "authenticate_and_enter_workspace.feature": """
Feature: Authenticate and enter DCFO workspace
  As a collections operator
  I need a secure session before operating late-fee workflows

  Scenario: Operator signs in with valid credentials
    Given an active operator account for the DCFO workspace
    When the operator submits valid credentials
    Then the operator is authenticated
    And the DCFO workspace dashboard is displayed with late-fee queue summary

  Scenario: Invalid credentials are rejected
    Given an active operator account for the DCFO workspace
    When the operator submits an invalid password
    Then authentication fails
    And the operator remains on the sign-in page with an error message
    And no late-fee job controls are available
""",
    "late_fee_assessment_journey.feature": """
Feature: Late fee assessment journey
  Assess overdue accounts through extract, validate, and apply stages

  Scenario: Late fee applied when payment is past grace period
    Given an account with payment due 20 days ago
    And grace period is configured as 10 days
    And the late fee rate is 5 percent
    When the late fee assessment job runs for the account
    Then the account is retrieved from the source payment ledger
    And payment age and grace rules are validated
    And a 5% late fee is applied to the outstanding balance
    And the fee application is recorded for audit

  Scenario: No late fee within configured grace period
    Given an account with payment due 5 days ago
    And grace period is configured as 10 days
    When the late fee assessment job runs for the account
    Then payment age and grace rules are validated
    And no late fee is applied to the balance
    And the account remains eligible for the next assessment cycle

  Scenario: Assessment stops when source payment data is unavailable
    Given an overdue account scheduled for late fee assessment
    And the source payment ledger is unavailable
    When the late fee assessment job runs for the account
    Then retrieval from the source payment ledger fails
    And the job does not apply a late fee
    And a recoverable failure is raised for retry
""",
    "admin_waiver_and_controls.feature": """
Feature: Admin waiver and fee controls
  Privileged admins may waive assessed late fees with full auditability

  Scenario: Fee waived for authorized admin override
    Given an overdue account with an applied late fee
    And an admin user with waiver permission
    When the admin waives the late fee with a documented reason
    Then the account balance has no late fee charge
    And an audit entry captures actor, reason, and timestamp

  Scenario: Unauthorized user cannot waive a late fee
    Given an overdue account with an applied late fee
    And an operator without waiver permission
    When the operator attempts to waive the late fee
    Then the waiver is rejected
    And the late fee charge remains on the balance
""",
    "stakeholder_notification.feature": """
Feature: Stakeholder notification after fee events
  Notify account owners when fees are applied or waived

  Scenario: Owner is notified when a late fee is applied
    Given a late fee was successfully applied to an account
    And the account has a registered feed owner email
    When notification dispatch runs
    Then the feed owner receives a communique describing the fee amount and due balance
    And notification delivery is marked complete

  Scenario: Notification is retried after transient delivery failure
    Given a late fee was successfully applied to an account
    And the notification service returns a transient failure
    When notification dispatch runs
    Then the system retries delivery within the recovery window
    And the account is not double-charged while retrying
""",
    "execution_monitor_and_history.feature": """
Feature: Execution monitor and fee history
  Operators need live progress and historical browse of fee actions

  Scenario: Operator monitors live late-fee job progress
    Given a late fee assessment job is in progress
    When the operator opens live progress for the job
    Then terminal and in-flight states are visible
    And failed accounts are listed with recoverable reasons

  Scenario: Operator browses historical fee actions for an account
    Given an account with prior late fee apply and waiver events
    When the operator opens fee history for the account
    Then apply and waiver events are listed with timestamps
    And each event links to its audit record
""",
    "ops_reporting_and_config_bootstrap.feature": """
Feature: Ops reporting and configuration bootstrap
  Job startup loads settings; ops can export fee metrics

  Scenario: Configuration is loaded before assessment jobs start
    Given DCFO settings document exists with grace days and fee rate
    When the late fee service initializes
    Then configuration is loaded successfully
    And assessment jobs use the configured grace days and fee rate

  Scenario: Ops exports a late-fee metrics report
    Given assessed and waived late fee events for the current period
    When an operations user exports the late-fee metrics report
    Then a metrics summary is produced for applied fees, waived fees, and failures
    And the export completes successfully
""",
}


def v2_requirement(unit: str, title: str, stories: list[str], shalls: list[str],
                   negatives: list[str] | None = None, extras: dict | None = None) -> str:
    negatives = negatives or []
    extras = extras or {}
    parts = [
        f"# {title}",
        "",
        f"**Unit:** `{unit}`",
        f"**Domain:** {DOMAIN}",
        "",
        "## Overview",
        extras.get(
            "overview",
            f"Specifies behavioural expectations for {title.lower()} within DCFO late-fee operations.",
        ),
        "",
        "## User Stories",
    ]
    for i, story in enumerate(stories, 1):
        parts.append(f"### US-{i:02d}")
        parts.append(story)
        parts.append("")
    parts.append("## Consolidated Requirements")
    for s in shalls:
        parts.append(f"- The system shall {s}")
    if negatives:
        parts.append("")
        parts.append("## Negative / Exception Paths")
        for n in negatives:
            parts.append(f"- {n}")
    parts.append("")
    parts.append("## Acceptance Criteria")
    for i, s in enumerate(shalls, 1):
        parts.append(f"- AC-{i}: Verify that the system {s}")
    if extras.get("data"):
        parts.append("")
        parts.append("## Data & Rules")
        parts.append(extras["data"])
    if extras.get("nfr"):
        parts.append("")
        parts.append("## Non-Functional")
        parts.append(extras["nfr"])
    return "\n".join(parts)


V2_REQUIREMENTS: dict[str, str] = {}

_v2_specs = [
    ("WF-auth", "Operator authentication",
     ["As an operator I want to sign in so that I can access late-fee controls."],
     ["authenticate operators with valid credentials",
      "reject invalid credentials without granting workspace access"],
     ["When credentials are invalid, the system must not expose late-fee job controls."]),
    ("WF-session", "Session and workspace entry",
     ["As an operator I want my session to land on the DCFO dashboard."],
     ["display the DCFO workspace dashboard after successful authentication",
      "include a late-fee queue summary on the dashboard"],
     []),
    ("WF-extract", "Payment ledger extract",
     ["As the assessment job I need source payment rows for overdue accounts."],
     ["retrieve account payment data from the source payment ledger",
      "mark retrieval failure when the ledger is unavailable"],
     ["If the source ledger is unavailable, assessment must stop without applying a fee."]),
    ("WF-validate-grace", "Grace period validation",
     ["As risk operations I need grace rules enforced before fees apply."],
     ["validate payment age against configured grace period",
      "skip fee application when payment age is within grace"],
     []),
    ("WF-apply-fee", "Late fee application",
     ["As collections I need overdue accounts charged at the configured rate."],
     ["apply the configured late fee percentage to the outstanding balance",
      "record fee application details for audit"],
     []),
    ("WF-no-fee", "Grace path no-fee",
     ["As a customer within grace I should not be charged a late fee."],
     ["leave the balance unchanged when grace validation fails the overdue rule"],
     []),
    ("WF-waiver-authz", "Waiver authorization",
     ["As security I need only authorized admins to waive fees."],
     ["allow fee waiver only for users with waiver permission",
      "reject waiver attempts from unauthorized operators"],
     ["Unauthorized waiver attempts must leave the late fee charge intact."]),
    ("WF-waiver-effect", "Waiver effect on balance",
     ["As an admin I waive a fee so the customer balance is corrected."],
     ["remove the late fee charge from the account balance after approved waiver",
      "capture actor, reason, and timestamp on waiver"],
     []),
    ("WF-notify-apply", "Notify on fee apply",
     ["As a feed owner I want notice when a late fee is applied."],
     ["send a communique to the registered feed owner after successful fee application",
      "include fee amount and due balance in the notification"],
     []),
    ("WF-notify-retry", "Notification retry",
     ["As reliability eng I need transient notification failures retried."],
     ["retry notification delivery after transient failures within the recovery window",
      "prevent double-charging while notification retries are in progress"],
     []),
    ("WF-monitor", "Live job monitoring",
     ["As an operator I monitor in-flight late-fee jobs."],
     ["expose live progress including in-flight and terminal job states",
      "list failed accounts with recoverable failure reasons"],
     []),
    ("WF-history", "Fee action history",
     ["As an operator I browse historical apply and waiver events."],
     ["list prior apply and waiver events with timestamps",
      "link each historical event to its audit record"],
     []),
    ("WF-config-boot", "Configuration bootstrap",
     ["As the service I load grace and rate settings before jobs run."],
     ["load DCFO settings document during service initialization",
      "use configured grace days and fee rate for assessment jobs"],
     ["If settings are missing, assessment jobs must not start."]),
    ("WF-report", "Ops metrics export",
     ["As operations I export applied, waived, and failed fee metrics."],
     ["produce a metrics summary for applied fees, waived fees, and failures",
      "complete metrics export successfully for the selected period"],
     []),
    ("WF-audit-apply", "Audit on apply",
     ["As compliance I need immutable apply audit records."],
     ["write an audit entry for every successful late fee application"],
     []),
    ("WF-audit-waiver", "Audit on waiver",
     ["As compliance I need immutable waiver audit records."],
     ["write an audit entry for every approved waiver including reason text"],
     []),
    ("WF-retry-job", "Recoverable assessment retry",
     ["As reliability eng I retry assessments after recoverable extract failures."],
     ["raise a recoverable failure when ledger extract fails",
      "allow assessment retry without applying duplicate fees"],
     []),
    ("WF-queue", "Late-fee work queue",
     ["As an operator I need overdue accounts queued for assessment."],
     ["enqueue eligible overdue accounts into the late-fee assessment queue"],
     []),
    ("WF-eligibility", "Assessment eligibility rules",
     ["As policy I define which accounts are eligible for assessment."],
     ["exclude accounts already waived in the current period from re-assessment",
      "include overdue accounts past grace that have not been assessed"],
     []),
    ("WF-rate-rules", "Fee rate business rules",
     ["As finance I configure the late fee percentage centrally."],
     ["read the late fee percentage from configuration rather than hard-coding",
      "apply the rate consistently across accounts in a job run"],
     []),
    ("WF-data-quality", "Payment data quality gates",
     ["As data ops I block fee apply when mandatory payment fields are missing."],
     ["validate mandatory payment fields before fee application",
      "reject assessment when mandatory fields are absent"],
     ["Missing mandatory payment fields must halt fee application for that account."]),
    ("WF-security-nfr", "Access control non-functionals",
     ["As security I require authenticated sessions for all fee controls."],
     ["require an authenticated session before late-fee controls are usable",
      "deny access to waiver and assessment controls for expired sessions"],
     []),
]

for unit, title, stories, shalls, negatives in _v2_specs:
    fname = f"{unit.lower().replace('_', '-')}-{title.lower().replace(' ', '-')[:28].rstrip('-')}.md"
    # Stable unique filenames
    fname = f"{unit}.md"
    V2_REQUIREMENTS[fname] = v2_requirement(
        unit,
        title,
        stories,
        shalls,
        negatives,
        extras={
            "data": (
                "Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, "
                "outstanding_balance, waiver_reason, notification_status."
            ),
            "nfr": (
                "Assessment and waiver actions must be auditable. Notification retries "
                "must be idempotent with respect to fee charges."
            ),
        },
    )


def main() -> None:
    v1_feat = ROOT / "v1" / "feature"
    v1_req = ROOT / "v1" / "requirements"
    v2_feat = ROOT / "v2" / "feature"
    v2_req = ROOT / "v2" / "requirements"

    for name, body in V1_FEATURES.items():
        write(v1_feat / name, body)
    for name, body in V1_REQUIREMENTS.items():
        write(v1_req / name, body)
    for name, body in V2_FEATURES.items():
        write(v2_feat / name, body)
    for name, body in V2_REQUIREMENTS.items():
        write(v2_req / name, body)

    print("v1 features", len(list(v1_feat.glob("*.feature"))))
    print("v1 requirements", len(list(v1_req.glob("*.md"))))
    print("v2 features", len(list(v2_feat.glob("*.feature"))))
    print("v2 requirements", len(list(v2_req.glob("*.md"))))


if __name__ == "__main__":
    main()
