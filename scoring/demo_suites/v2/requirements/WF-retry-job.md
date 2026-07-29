# Recoverable assessment retry

**Unit:** `WF-retry-job`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for recoverable assessment retry within DCFO late-fee operations.

## User Stories
### US-01
As reliability eng I retry assessments after recoverable extract failures.

## Consolidated Requirements
- The system shall raise a recoverable failure when ledger extract fails
- The system shall allow assessment retry without applying duplicate fees

## Acceptance Criteria
- AC-1: Verify that the system raise a recoverable failure when ledger extract fails
- AC-2: Verify that the system allow assessment retry without applying duplicate fees

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
