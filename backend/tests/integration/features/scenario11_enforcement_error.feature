Feature: Enforcement-path failure fails closed, never open
  # spec.md Scenario 11

  Scenario: Enforcement-path failure fails closed, never open
    Given the classification pipeline runs for domain "healthcare"
    And the policy for domain "healthcare" is published
    And the active policy file for domain "healthcare" becomes corrupted
    When an analyst submits the SQL query "SELECT patient_ssn FROM patients" to domain "healthcare"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "ENFORCEMENT_ERROR" with message "enforcement error: unable to evaluate policy for this query"
