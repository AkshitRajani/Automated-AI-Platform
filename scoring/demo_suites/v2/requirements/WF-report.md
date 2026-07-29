# Ops metrics export

**Unit:** `WF-report`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for ops metrics export within DCFO late-fee operations.

## User Stories
### US-01
As operations I export applied, waived, and failed fee metrics.

## Consolidated Requirements
- The system shall produce a metrics summary for applied fees, waived fees, and failures
- The system shall complete metrics export successfully for the selected period

## Acceptance Criteria
- AC-1: Verify that the system produce a metrics summary for applied fees, waived fees, and failures
- AC-2: Verify that the system complete metrics export successfully for the selected period

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
