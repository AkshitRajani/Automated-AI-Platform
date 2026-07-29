# Assessment eligibility rules

**Unit:** `WF-eligibility`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for assessment eligibility rules within DCFO late-fee operations.

## User Stories
### US-01
As policy I define which accounts are eligible for assessment.

## Consolidated Requirements
- The system shall exclude accounts already waived in the current period from re-assessment
- The system shall include overdue accounts past grace that have not been assessed

## Acceptance Criteria
- AC-1: Verify that the system exclude accounts already waived in the current period from re-assessment
- AC-2: Verify that the system include overdue accounts past grace that have not been assessed

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
