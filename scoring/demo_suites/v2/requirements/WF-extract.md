# Payment ledger extract

**Unit:** `WF-extract`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for payment ledger extract within DCFO late-fee operations.

## User Stories
### US-01
As the assessment job I need source payment rows for overdue accounts.

## Consolidated Requirements
- The system shall retrieve account payment data from the source payment ledger
- The system shall mark retrieval failure when the ledger is unavailable

## Negative / Exception Paths
- If the source ledger is unavailable, assessment must stop without applying a fee.

## Acceptance Criteria
- AC-1: Verify that the system retrieve account payment data from the source payment ledger
- AC-2: Verify that the system mark retrieval failure when the ledger is unavailable

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
