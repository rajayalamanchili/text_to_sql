Feature: Obvious PII column is classified correctly
  # spec.md Scenario 1

  Scenario: Obvious PII column is classified correctly
    Given a healthcare schema containing a column "patients.patient_ssn" (string, near-100% unique values)
    When the classification pipeline runs for domain "healthcare"
    Then the column "patients.patient_ssn" is classified "pii_direct" with confidence >= 0.9
    And no human review is triggered for "patients.patient_ssn" in domain "healthcare"
    And the published policy for domain "healthcare" sets "block" for "patients.patient_ssn"
