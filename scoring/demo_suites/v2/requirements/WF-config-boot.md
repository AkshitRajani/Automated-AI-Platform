# Configuration bootstrap

**Unit:** `WF-config-boot`
**Domain:** DCFO late fee and payment operations

## Overview
Specifies behavioural expectations for configuration bootstrap within DCFO late-fee operations.

## User Stories
### US-01
As the service I load grace and rate settings before jobs run.

## Consolidated Requirements
- The system shall load DCFO settings document during service initialization
- The system shall use configured grace days and fee rate for assessment jobs

## Negative / Exception Paths
- If settings are missing, assessment jobs must not start.

## Acceptance Criteria
- AC-1: Verify that the system load DCFO settings document during service initialization
- AC-2: Verify that the system use configured grace days and fee rate for assessment jobs

## Data & Rules
Key fields: account_id, payment_due_date, grace_days, fee_rate_pct, outstanding_balance, waiver_reason, notification_status.

## Non-Functional
Assessment and waiver actions must be auditable. Notification retries must be idempotent with respect to fee charges.
