Feature: Stakeholder notification after fee events
  Notify account owners when fees are applied or waived

  Scenario: Owner is notified when a late fee is applied
    Given a late fee was successfully applied to an account
    And the account has a registered feed owner email
    When notification dispatch runs
    Then the feed owner receives a communique describing the fee amount and due balance
    And notification delivery is marked complete

  Scenario: Notification is retried after transient delivery failure
    Given a late fee was successfully applied to an account
    And the notification service returns a transient failure
    When notification dispatch runs
    Then the system retries delivery within the recovery window
    And the account is not double-charged while retrying
