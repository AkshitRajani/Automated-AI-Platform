# Waiver authorization

**Unit:** `WF-waiver-authz`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for waiver authorization within DCFO late-fee operations.

## User Stories
### US-01
As security I need only authorized admins to waive fees.

## Consolidated Requirements
- The system shall allow fee waiver only for users with waiver permission
- The system shall reject waiver attempts from unauthorized operators

## Negative / Exception Paths
- Unauthorized waiver attempts must leave the late fee charge intact.

## Acceptance Criteria
- AC-1: Verify that the system allow fee waiver only for users with waiver permission
- AC-2: Verify that the system reject waiver attempts from unauthorized operators

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
