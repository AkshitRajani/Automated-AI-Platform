# Late fee application

**Unit:** `WF-apply-fee`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for late fee application within DCFO late-fee operations.

## User Stories
### US-01
As collections I need overdue accounts charged at the configured rate.

## Consolidated Requirements
- The system shall apply the configured late fee percentage to the outstanding balance
- The system shall record fee application details for audit

## Acceptance Criteria
- AC-1: Verify that the system apply the configured late fee percentage to the outstanding balance
- AC-2: Verify that the system record fee application details for audit

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
