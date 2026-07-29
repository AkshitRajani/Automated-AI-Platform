# Fee action history

**Unit:** `WF-history`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for fee action history within DCFO late-fee operations.

## User Stories
### US-01
As an operator I browse historical apply and waiver events.

## Consolidated Requirements
- The system shall list prior apply and waiver events with timestamps
- The system shall link each historical event to its audit record

## Acceptance Criteria
- AC-1: Verify that the system list prior apply and waiver events with timestamps
- AC-2: Verify that the system link each historical event to its audit record

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
