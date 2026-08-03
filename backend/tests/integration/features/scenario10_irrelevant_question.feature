Feature: Irrelevant question does not leak schema or bypass enforcement
  # spec.md Scenario 10

  Scenario: Irrelevant question does not leak schema or bypass enforcement
    Given the classification pipeline runs for domain "healthcare"
    And the policy for domain "healthcare" is published
    When an analyst asks the question "what is the weather today?" of domain "healthcare"
    Then the question is not executed as SQL against domain "healthcare"
    And the response indicates reason code "QUESTION_NOT_MAPPED" with message "question not mapped to schema"
    And the response does not reveal any table or column name from domain "healthcare"
