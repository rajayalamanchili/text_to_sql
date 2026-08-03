Feature: Row-level policy is applied regardless of LLM-generated predicates
  # spec.md Scenario 5

  Scenario: Row-level policy predicate is AND-merged with the LLM's SQL and enforced
    Given the classification pipeline runs for domain "fintech"
    And the column "claims.tenant_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_status" is approved as "business" in domain "fintech"
    And the policy for domain "fintech" is published
    And the "claims" table has a row policy "tenant_id = :current_tenant" in domain "fintech"
    And domain "fintech" has "approved" claims for tenant "tenant-001" and at least one other tenant
    When a caller with tenant "tenant-001" submits the SQL query "SELECT tenant_id, claim_id, claim_status FROM claims WHERE claim_status = 'approved'" to domain "fintech"
    Then the query succeeds with status 200
    And every returned row belongs to tenant "tenant-001" with claim_status "approved"
    And fewer rows are returned than the total number of matching claims across all tenants

  Scenario: Missing tenant header on a tenant-scoped table fails closed
    Given the classification pipeline runs for domain "fintech"
    And the column "claims.tenant_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_status" is approved as "business" in domain "fintech"
    And the policy for domain "fintech" is published
    And the "claims" table has a row policy "tenant_id = :current_tenant" in domain "fintech"
    When a caller with no tenant header submits the SQL query "SELECT tenant_id, claim_id FROM claims" to domain "fintech"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "ENFORCEMENT_ERROR" with message "enforcement error: unable to evaluate policy for this query"

  Scenario: Blank tenant header on a tenant-scoped table fails closed
    Given the classification pipeline runs for domain "fintech"
    And the column "claims.tenant_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_id" is approved as "business" in domain "fintech"
    And the column "claims.claim_status" is approved as "business" in domain "fintech"
    And the policy for domain "fintech" is published
    And the "claims" table has a row policy "tenant_id = :current_tenant" in domain "fintech"
    When a caller with tenant "   " submits the SQL query "SELECT tenant_id, claim_id FROM claims" to domain "fintech"
    Then the query is rejected before execution with status 403
    And the rejection reason code is "ENFORCEMENT_ERROR" with message "enforcement error: unable to evaluate policy for this query"
