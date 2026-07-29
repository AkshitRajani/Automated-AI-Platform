Feature: Admin waiver and fee controls
  Privileged admins may waive assessed late fees with full auditability

  Scenario: Fee waived for authorized admin override
    Given an overdue account with an applied late fee
    And an admin user with waiver permission
    When the admin waives the late fee with a documented reason
    Then the account balance has no late fee charge
    And an audit entry captures actor, reason, and timestamp

  Scenario: Unauthorized user cannot waive a late fee
    Given an overdue account with an applied late fee
    And an operator without waiver permission
    When the operator attempts to waive the late fee
    Then the waiver is rejected
    And the late fee charge remains on the balance
