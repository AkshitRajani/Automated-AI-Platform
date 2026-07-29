# Access control non-functionals

**Unit:** `WF-security-nfr`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for access control non-functionals within DCFO late-fee operations.

## User Stories
### US-01
As security I require authenticated sessions for all fee controls.

## Consolidated Requirements
- The system shall require an authenticated session before late-fee controls are usable
- The system shall deny access to waiver and assessment controls for expired sessions

## Acceptance Criteria
- AC-1: Verify that the system require an authenticated session before late-fee controls are usable
- AC-2: Verify that the system deny access to waiver and assessment controls for expired sessions

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
