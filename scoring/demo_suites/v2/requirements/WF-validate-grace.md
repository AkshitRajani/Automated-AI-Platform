# Grace period validation

**Unit:** `WF-validate-grace`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for grace period validation within DCFO late-fee operations.

## User Stories
### US-01
As risk operations I need grace rules enforced before fees apply.

## Consolidated Requirements
- The system shall validate payment age against configured grace period
- The system shall skip fee application when payment age is within grace

## Acceptance Criteria
- AC-1: Verify that the system validate payment age against configured grace period
- AC-2: Verify that the system skip fee application when payment age is within grace

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
