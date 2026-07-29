Feature: Late fee
  Scenario: apply fee
    Given overdue
    When job runs
    Then fee added
