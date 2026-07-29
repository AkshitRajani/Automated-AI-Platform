Feature: Audit
  Scenario: log change
    When fee change
    Then log row
