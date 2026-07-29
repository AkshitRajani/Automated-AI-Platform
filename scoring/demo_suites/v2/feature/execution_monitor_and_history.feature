Feature: Execution monitor and fee history
  Operators need live progress and historical browse of fee actions

  Scenario: Operator monitors live late-fee job progress
    Given a late fee assessment job is in progress
    When the operator opens live progress for the job
    Then terminal and in-flight states are visible
    And failed accounts are listed with recoverable reasons

  Scenario: Operator browses historical fee actions for an account
    Given an account with prior late fee apply and waiver events
    When the operator opens fee history for the account
    Then apply and waiver events are listed with timestamps
    And each event links to its audit record
