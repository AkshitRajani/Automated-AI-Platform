# Fee rate business rules

**Unit:** `WF-rate-rules`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for fee rate business rules within DCFO late-fee operations.

## User Stories
### US-01
As finance I configure the late fee percentage centrally.

## Consolidated Requirements
- The system shall read the late fee percentage from configuration rather than hard-coding
- The system shall apply the rate consistently across accounts in a job run

## Acceptance Criteria
- AC-1: Verify that the system read the late fee percentage from configuration rather than hard-coding
- AC-2: Verify that the system apply the rate consistently across accounts in a job run

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
