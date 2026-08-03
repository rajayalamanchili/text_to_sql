Feature: Adversarially-named column is not misclassified as safe
  # spec.md Scenario 3

  Scenario: Adversarially-named column is not misclassified as safe
    Given a healthcare schema containing a column "patients.patient_notes" that contains free-text clinical narrative
    When the classification pipeline runs for domain "healthcare"
    Then the column "patients.patient_notes" is NOT auto-classified "business" with high confidence
    And "patients.patient_notes" is either classified "sensitive_category" or routed to human review
