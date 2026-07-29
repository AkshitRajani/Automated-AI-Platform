Feature: Late fee assessment journey
  Assess overdue accounts through extract, validate, and apply stages

  Scenario: Late fee applied when payment is past grace period
    Given an account with payment due 20 days ago
    And grace period is configured as 10 days
    And the late fee rate is 5 percent
    When the late fee assessment job runs for the account
    Then the account is retrieved from the source payment ledger
    And payment age and grace rules are validated
    And a 5% late fee is applied to the outstanding balance
    And the fee application is recorded for audit

  Scenario: No late fee within configured grace period
    Given an account with payment due 5 days ago
    And grace period is configured as 10 days
    When the late fee assessment job runs for the account
    Then payment age and grace rules are validated
    And no late fee is applied to the balance
    And the account remains eligible for the next assessment cycle

  Scenario: Assessment stops when source payment data is unavailable
    Given an overdue account scheduled for late fee assessment
    And the source payment ledger is unavailable
    When the late fee assessment job runs for the account
    Then retrieval from the source payment ledger fails
    And the job does not apply a late fee
    And a recoverable failure is raised for retry
