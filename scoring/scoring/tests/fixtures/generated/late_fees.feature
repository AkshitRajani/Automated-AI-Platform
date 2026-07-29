Feature: Late fees
  Scenario: Apply late fee on overdue payment
    Given account "ACC-001" has overdue payment of 20 days
    When late_fee_handler is invoked
    Then the account balance includes a 5 percent late fee

  Scenario: Grace period excludes late fee
    Given account "ACC-002" has overdue payment of 5 days
    When late_fee_handler is invoked
    Then the account balance has no late fee

Feature: Payments
  Scenario: Duplicate payment rejected
    Given account "ACC-003" has an open invoice
    When a duplicate payment is submitted
    Then the payment is rejected with a duplicate error
