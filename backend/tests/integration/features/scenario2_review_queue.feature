Feature: Ambiguous column is flagged for human review
  # spec.md Scenario 2

  Scenario: Ambiguous column is flagged for human review
    Given a fintech schema containing a column "transactions.notes" (free text, low cardinality of distinct patterns)
    When the classification pipeline runs for domain "fintech"
    Then the column "transactions.notes" receives a classification with confidence < 0.85
    And the column "transactions.notes" is added to the human-review queue for domain "fintech"
    And a reviewer sees "transactions.notes" in the review UI with status "pending_review"
    And the policy status for "transactions.notes" is "pending_review", not "allowed", until an admin approves it
