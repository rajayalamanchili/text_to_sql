Feature: LLM-proposed DML statement is rejected unconditionally
  # spec.md Scenario 9

  Scenario: LLM-proposed DML statement is rejected unconditionally
    Given the classification pipeline runs for domain "fintech"
    And the policy for domain "fintech" is published
    When an analyst submits the SQL query "DELETE FROM transactions WHERE id = 1" to domain "fintech"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "DML_REJECTED" with message "DML statement rejected: read-only queries only"

  Scenario: Stacked multi-statement input is rejected before any DML/policy check
    Given the classification pipeline runs for domain "fintech"
    And the policy for domain "fintech" is published
    When an analyst submits the SQL query "SELECT * FROM transactions; DROP TABLE transactions;" to domain "fintech"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "MULTIPLE_STATEMENTS_REJECTED" with message "multiple statements rejected: only a single read-only query is allowed"
