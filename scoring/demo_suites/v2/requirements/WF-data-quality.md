# Payment data quality gates

**Unit:** `WF-data-quality`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for payment data quality gates within DCFO late-fee operations.

## User Stories
### US-01
As data ops I block fee apply when mandatory payment fields are missing.

## Consolidated Requirements
- The system shall validate mandatory payment fields before fee application
- The system shall reject assessment when mandatory fields are absent

## Negative / Exception Paths
- Missing mandatory payment fields must halt fee application for that account.

## Acceptance Criteria
- AC-1: Verify that the system validate mandatory payment fields before fee application
- AC-2: Verify that the system reject assessment when mandatory fields are absent

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
