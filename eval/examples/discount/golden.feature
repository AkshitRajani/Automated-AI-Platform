Feature: Discount pricing

  Scenario: Member gets a discount
    Given an order with total 100
    And the customer is a member
    When the discount is applied
    Then the charge is 90.0

  Scenario: Non-member pays full price
    Given an order with total 100
    And the customer is not a member
    When the discount is applied
    Then the charge is 100

  Scenario: Order qualifies for eligibility
    Given an order with total 100
    Then the order is eligible for discount

  Scenario: Order does not qualify for eligibility
    Given an order with total 99
    Then the order is not eligible for discount
