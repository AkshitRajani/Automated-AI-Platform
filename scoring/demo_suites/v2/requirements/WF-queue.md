# Late-fee work queue

**Unit:** `WF-queue`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for late-fee work queue within DCFO late-fee operations.

## User Stories
### US-01
As an operator I need overdue accounts queued for assessment.

## Consolidated Requirements
- The system shall enqueue eligible overdue accounts into the late-fee assessment queue

## Acceptance Criteria
- AC-1: Verify that the system enqueue eligible overdue accounts into the late-fee assessment queue

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
