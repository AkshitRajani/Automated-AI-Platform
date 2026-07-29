# Notification retry

**Unit:** `WF-notify-retry`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for notification retry within DCFO late-fee operations.

## User Stories
### US-01
As reliability eng I need transient notification failures retried.

## Consolidated Requirements
- The system shall retry notification delivery after transient failures within the recovery window
- The system shall prevent double-charging while notification retries are in progress

## Acceptance Criteria
- AC-1: Verify that the system retry notification delivery after transient failures within the recovery window
- AC-2: Verify that the system prevent double-charging while notification retries are in progress

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
