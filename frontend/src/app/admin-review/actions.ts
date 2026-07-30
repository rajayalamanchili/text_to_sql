// Review-queue mutations (contracts/api.md), typed against the backend's
// generated OpenAPI schema (tech-stack.md) via `./types`.

import type { ColumnClassification, ReclassifyRequest } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

type ReviewAction = "approve" | "reject" | "reclassify";

async function describeError(res: Response, action: ReviewAction): Promise<string> {
  const body: unknown = await res.json().catch(() => null);
  if (body && typeof body === "object") {
    if ("error" in body && typeof body.error === "string") return body.error;
    if ("detail" in body && typeof body.detail === "string") return body.detail;
  }
  return `${action} request failed with status ${res.status}`;
}

async function postReviewAction(
  domain: string,
  columnId: string,
  action: ReviewAction,
  role: string,
  body?: ReclassifyRequest,
): Promise<ColumnClassification> {
  const res = await fetch(`${API_BASE_URL}/domains/${domain}/review-queue/${columnId}/${action}`, {
    method: "POST",
    headers: {
      "X-Steward-Role": role,
      ...(body ? { "Content-Type": "application/json" } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    throw new Error(await describeError(res, action));
  }

  return (await res.json()) as ColumnClassification;
}

// Admin-only (contracts/api.md); a non-admin `role` gets a 403 from the
// backend, which surfaces as a rejected promise here — this module does
// not pre-check the role itself (enforcement lives server-side, not in
// the UI).
export function approveColumn(
  domain: string,
  columnId: string,
  role: string,
): Promise<ColumnClassification> {
  return postReviewAction(domain, columnId, "approve", role);
}

export function rejectColumn(
  domain: string,
  columnId: string,
  role: string,
): Promise<ColumnClassification> {
  return postReviewAction(domain, columnId, "reject", role);
}

export function reclassifyColumn(
  domain: string,
  columnId: string,
  role: string,
  classification: ReclassifyRequest["classification"],
): Promise<ColumnClassification> {
  return postReviewAction(domain, columnId, "reclassify", role, { classification });
}
