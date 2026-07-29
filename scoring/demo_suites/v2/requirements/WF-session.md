# Session and workspace entry

**Unit:** `WF-session`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for session and workspace entry within DCFO late-fee operations.

## User Stories
### US-01
As an operator I want my session to land on the DCFO dashboard.

## Consolidated Requirements
- The system shall display the DCFO workspace dashboard after successful authentication
- The system shall include a late-fee queue summary on the dashboard

## Acceptance Criteria
- AC-1: Verify that the system display the DCFO workspace dashboard after successful authentication
- AC-2: Verify that the system include a late-fee queue summary on the dashboard

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
