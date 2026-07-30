Feature: Unclassified column defaults to blocked, not allowed
  # spec.md Scenario 6

  Scenario: Unclassified column defaults to blocked, not allowed
    Given the classification pipeline runs for domain "healthcare"
    And the policy for domain "healthcare" is published
    When an analyst submits the SQL query "SELECT * FROM new_unclassified_table" to domain "healthcare"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "NO_ACTIVE_POLICY" with message "schema not yet classified"
    And no rows from domain "healthcare" are returned in the response
