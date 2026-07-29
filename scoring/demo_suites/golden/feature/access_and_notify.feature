Feature: Operator access and notifications
  Manual ground-truth for sign-in and stakeholder notify paths

  Scenario: Operator signs in with valid credentials
    Given an active operator account for the DCFO workspace
    When the operator submits valid credentials
    Then the operator is authenticated
    And the DCFO workspace dashboard is displayed

  Scenario: Owner is notified when a late fee is applied
    Given a late fee was successfully applied to an account
    And the account has a registered feed owner email
    When notification dispatch runs
    Then the feed owner receives a communique describing the fee amount and due balance
