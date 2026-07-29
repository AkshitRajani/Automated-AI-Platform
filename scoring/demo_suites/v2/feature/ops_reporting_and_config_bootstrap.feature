Feature: Ops reporting and configuration bootstrap
  Job startup loads settings; ops can export fee metrics

  Scenario: Configuration is loaded before assessment jobs start
    Given DCFO settings document exists with grace days and fee rate
    When the late fee service initializes
    Then configuration is loaded successfully
    And assessment jobs use the configured grace days and fee rate

  Scenario: Ops exports a late-fee metrics report
    Given assessed and waived late fee events for the current period
    When an operations user exports the late-fee metrics report
    Then a metrics summary is produced for applied fees, waived fees, and failures
    And the export completes successfully
