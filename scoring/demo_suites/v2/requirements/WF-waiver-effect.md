# Waiver effect on balance

**Unit:** `WF-waiver-effect`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for waiver effect on balance within DCFO late-fee operations.

## User Stories
### US-01
As an admin I waive a fee so the customer balance is corrected.

## Consolidated Requirements
- The system shall remove the late fee charge from the account balance after approved waiver
- The system shall capture actor, reason, and timestamp on waiver

## Acceptance Criteria
- AC-1: Verify that the system remove the late fee charge from the account balance after approved waiver
- AC-2: Verify that the system capture actor, reason, and timestamp on waiver

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
