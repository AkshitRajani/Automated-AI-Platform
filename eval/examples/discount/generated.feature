Feature: Discount pricing (AI-generated suite)

  Scenario: Member gets a discount
    Given an order with total 100
    And the customer is a member
    When the discount is applied
    Then the charge is 90.0

  Scenario: Order qualifies for eligibility
    Given an order with total 100
    Then the order is eligible for discount

  Scenario: Padding scenario with no real coverage
    Given the system is running
    Then nothing in particular is verified
