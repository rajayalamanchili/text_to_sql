"use client";

import { useEffect, useState } from "react";
import { ReviewQueueTable } from "./components/ReviewQueueTable";
import type { ColumnClassification } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

// The two domains configured for this milestone (CLAUDE.md). This is a
// UI-only selector list, not engine logic — the backend itself discovers
// domains from `domains/`'s subdirectories rather than any hardcoded name
// (FR-011); there is no `GET /domains` listing endpoint to derive this from.
const DOMAINS = ["healthcare", "fintech"] as const;
type Domain = (typeof DOMAINS)[number];

// Milestone 1 has no real identity provider (tech-stack.md Auth) — the
// caller's role is whatever `X-Steward-Role` is sent on the request. This
// selector lets a reviewer demo both the analyst and admin experience
// without a login flow; it is not a security boundary.
const ROLES = ["analyst", "admin"] as const;
type Role = (typeof ROLES)[number];

// Keyed by the (domain, role) it was fetched for, so staleness — and
// therefore the "loading" state below — can be derived during render
// instead of via a separate boolean set synchronously inside the effect.
interface FetchResult {
  domain: Domain;
  role: Role;
  items: ColumnClassification[];
  error: string | null;
}

export default function AdminReviewPage() {
  const [domain, setDomain] = useState<Domain>(DOMAINS[0]);
  const [role, setRole] = useState<Role>("analyst");
  const [result, setResult] = useState<FetchResult | null>(null);

  useEffect(() => {
    const controller = new AbortController();

    fetch(`${API_BASE_URL}/domains/${domain}/review-queue`, {
      headers: { "X-Steward-Role": role },
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`review-queue request failed with status ${res.status}`);
        }
        const body = (await res.json()) as { items: ColumnClassification[] };
        setResult({ domain, role, items: body.items, error: null });
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setResult({
          domain,
          role,
          items: [],
          error: err instanceof Error ? err.message : "failed to load review queue",
        });
      });

    return () => controller.abort();
  }, [domain, role]);

  const isStale = result === null || result.domain !== domain || result.role !== role;
  const items = isStale ? [] : result.items;
  const error = isStale ? null : result.error;
  const status: "loading" | "loaded" | "error" = isStale ? "loading" : error ? "error" : "loaded";

  function handleResolved(columnId: string) {
    setResult((prev) =>
      prev ? { ...prev, items: prev.items.filter((item) => item.id !== columnId) } : prev,
    );
  }

  return (
    <div className="flex flex-1 flex-col gap-6 p-8">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold text-zinc-950 dark:text-zinc-50">
          Human Review Queue
        </h1>
        <p className="text-sm text-zinc-600 dark:text-zinc-400">
          Columns pending classification review (FR-013).
        </p>
      </header>

      <div className="flex flex-wrap items-end gap-4">
        <label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
          Domain
          <select
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            value={domain}
            onChange={(e) => setDomain(e.target.value as Domain)}
          >
            {DOMAINS.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>

        <label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
          Caller role (auth stub)
          <select
            className="rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
            value={role}
            onChange={(e) => setRole(e.target.value as Role)}
          >
            {ROLES.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
      </div>

      {status === "loading" && <p className="text-sm text-zinc-500">Loading review queue…</p>}

      {status === "error" && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}

      {status === "loaded" && items.length === 0 && (
        <p className="text-sm text-zinc-500">No columns pending review for {domain}.</p>
      )}

      {status === "loaded" && items.length > 0 && role !== "admin" && (
        <p className="text-sm text-zinc-500">
          Viewing as analyst — switch to admin to approve, reject, or reclassify.
        </p>
      )}

      {status === "loaded" && items.length > 0 && (
        <ReviewQueueTable
          domain={domain}
          role={role}
          canReview={role === "admin"}
          items={items}
          onResolved={handleResolved}
        />
      )}
    </div>
  );
}
