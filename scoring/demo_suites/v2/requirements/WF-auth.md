# Operator authentication

**Unit:** `WF-auth`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for operator authentication within DCFO late-fee operations.

## User Stories
### US-01
As an operator I want to sign in so that I can access late-fee controls.

## Consolidated Requirements
- The system shall authenticate operators with valid credentials
- The system shall reject invalid credentials without granting workspace access

## Negative / Exception Paths
- When credentials are invalid, the system must not expose late-fee job controls.

## Acceptance Criteria
- AC-1: Verify that the system authenticate operators with valid credentials
- AC-2: Verify that the system reject invalid credentials without granting workspace access

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
