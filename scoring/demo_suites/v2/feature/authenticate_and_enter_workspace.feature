Feature: Authenticate and enter DCFO workspace
  As a collections operator
  I need a secure session before operating late-fee workflows

  Scenario: Operator signs in with valid credentials
    Given an active operator account for the DCFO workspace
    When the operator submits valid credentials
    Then the operator is authenticated
    And the DCFO workspace dashboard is displayed with late-fee queue summary

  Scenario: Invalid credentials are rejected
    Given an active operator account for the DCFO workspace
    When the operator submits an invalid password
    Then authentication fails
    And the operator remains on the sign-in page with an error message
    And no late-fee job controls are available
