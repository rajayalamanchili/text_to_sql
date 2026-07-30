// Re-exports the backend-generated OpenAPI schema types (tech-stack.md:
// "keeps frontend/backend contract in sync automatically rather than
// hand-maintained, reducing drift risk"). Regenerate `../../services/api-types.ts`
// via `npm run generate:api-types` after any backend response-model change.

import type { components } from "@/services/api-types";

export type Classification = components["schemas"]["Classification"];
export type ClassificationSource = components["schemas"]["ClassificationSource"];
export type ClassificationStatus = components["schemas"]["ClassificationStatus"];
export type ColumnClassification = components["schemas"]["ColumnClassification"];
export type ReclassifyRequest = components["schemas"]["ReclassifyRequest"];
