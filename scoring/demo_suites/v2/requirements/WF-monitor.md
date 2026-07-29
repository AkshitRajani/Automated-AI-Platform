# Live job monitoring

**Unit:** `WF-monitor`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for live job monitoring within DCFO late-fee operations.

## User Stories
### US-01
As an operator I monitor in-flight late-fee jobs.

## Consolidated Requirements
- The system shall expose live progress including in-flight and terminal job states
- The system shall list failed accounts with recoverable failure reasons

## Acceptance Criteria
- AC-1: Verify that the system expose live progress including in-flight and terminal job states
- AC-2: Verify that the system list failed accounts with recoverable failure reasons

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
