Feature: Only an admin can approve a pending classification
  # spec.md Scenario 8

  Scenario: Only an admin can approve a pending classification
    Given a fintech schema containing a column "transactions.notes" (free text, low cardinality of distinct patterns)
    And the classification pipeline runs for domain "fintech"
    And the column "transactions.notes" is in the review queue for domain "fintech"
    When an analyst attempts to approve "transactions.notes" in domain "fintech"
    Then the approval is rejected with status 403
    And the column "transactions.notes" remains "pending_review" in domain "fintech"
    When an admin approves "transactions.notes" in domain "fintech"
    Then the approval succeeds
    And the column "transactions.notes" is "approved" in domain "fintech"
    And the audit log records the admin's identity for the approval in domain "fintech"
