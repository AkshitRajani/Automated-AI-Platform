# Notify on fee apply

**Unit:** `WF-notify-apply`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for notify on fee apply within DCFO late-fee operations.

## User Stories
### US-01
As a feed owner I want notice when a late fee is applied.

## Consolidated Requirements
- The system shall send a communique to the registered feed owner after successful fee application
- The system shall include fee amount and due balance in the notification

## Acceptance Criteria
- AC-1: Verify that the system send a communique to the registered feed owner after successful fee application
- AC-2: Verify that the system include fee amount and due balance in the notification

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
