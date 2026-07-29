Feature: Late fees
  @regression
  Scenario: Late fee when payment is overdue
    Given an account with payment due 20 days ago
    When the late fee job runs
    Then a 5% late fee is applied to the balance

  Scenario: No late fee within grace period
    Given an account with payment due 5 days ago
    When the late fee job runs
    Then no late fee is applied to the balance

Feature: Admin overrides
  Scenario: Fee waived for admin override
    Given an overdue account
    And an admin with waiver permission
    When the admin waives the late fee
    Then the account balance has no late fee charge
