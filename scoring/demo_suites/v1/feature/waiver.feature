Feature: Waiver
  Scenario: waive
    Given admin
    When waive
    Then balance fixed
