Feature: Skip fee
  Scenario: no fee
    Given recent payment due
    When job
    Then nothing
