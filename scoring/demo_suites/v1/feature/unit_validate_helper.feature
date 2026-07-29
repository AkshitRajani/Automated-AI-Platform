Feature: Helper validate
  # noise: looks like a unit test, not a business journey
  Scenario: null check
    Given null input
    When validate helper called
    Then returns false
