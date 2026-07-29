Feature: Retry
  Scenario: retry fail
    Given error
    When retry
    Then maybe works
