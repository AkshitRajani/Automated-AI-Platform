# Audit on apply

**Unit:** `WF-audit-apply`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for audit on apply within DCFO late-fee operations.

## User Stories
### US-01
As compliance I need immutable apply audit records.

## Consolidated Requirements
- The system shall write an audit entry for every successful late fee application

## Acceptance Criteria
- AC-1: Verify that the system write an audit entry for every successful late fee application

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
