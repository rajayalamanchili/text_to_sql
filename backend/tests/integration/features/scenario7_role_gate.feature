Feature: Role-gated column is visible only to the correct role
  # spec.md Scenario 7

  Scenario: Role-gated column rejects the wrong role and allows the correct one
    Given the classification pipeline runs for domain "healthcare"
    And the policy for domain "healthcare" is published
    And the "patients.diagnosis_code" column is role-gated to "admin" in domain "healthcare"
    When a caller with role "analyst" submits the SQL query "SELECT diagnosis_code FROM patients" to domain "healthcare"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "ROLE_GATE_MISMATCH" with message "column requires role: admin"
    When a caller with role "admin" submits the SQL query "SELECT diagnosis_code FROM patients" to domain "healthcare"
    Then the query succeeds with status 200
