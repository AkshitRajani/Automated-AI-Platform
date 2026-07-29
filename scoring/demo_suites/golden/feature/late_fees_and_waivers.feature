Feature: Late fees
  Manual ground-truth coverage for DCFO late-fee assessment

  Scenario: Late fee when payment is overdue
    Given an account with payment due 20 days ago
    And grace period is configured as 10 days
    When the late fee assessment job runs for the account
    Then a 5% late fee is applied to the outstanding balance
    And the fee application is recorded for audit

  Scenario: No late fee within grace period
    Given an account with payment due 5 days ago
    And grace period is configured as 10 days
    When the late fee assessment job runs for the account
    Then no late fee is applied to the balance

Feature: Admin overrides
  Scenario: Fee waived for admin override
    Given an overdue account with an applied late fee
    And an admin user with waiver permission
    When the admin waives the late fee with a documented reason
    Then the account balance has no late fee charge
    And an audit entry captures actor, reason, and timestamp

  Scenario: Unauthorized waiver is rejected
    Given an overdue account with an applied late fee
    And an operator without waiver permission
    When the operator attempts to waive the late fee
    Then the waiver is rejected
    And the late fee charge remains on the balance
