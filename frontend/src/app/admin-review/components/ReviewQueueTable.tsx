"use client";

import { useState } from "react";
import { approveColumn, rejectColumn, reclassifyColumn } from "../actions";
import type { Classification, ColumnClassification } from "../types";

const thClass = "px-4 py-2 text-left font-medium text-zinc-600 dark:text-zinc-300";
const tdClass = "px-4 py-2 text-zinc-800 dark:text-zinc-200";
const buttonClass =
  "rounded-md border border-zinc-300 px-2 py-1 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700";

const CLASSIFICATIONS: Classification[] = [
  "pii_direct",
  "pii_indirect",
  "sensitive_category",
  "business",
  "unclassified",
];

function formatScore(score: number | null | undefined): string {
  return score === null || score === undefined ? "—" : score.toFixed(2);
}

export function ReviewQueueTable({
  domain,
  role,
  canReview,
  items,
  onResolved,
}: {
  domain: string;
  role: string;
  canReview: boolean;
  items: ColumnClassification[];
  onResolved: (columnId: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-md border border-zinc-200 dark:border-zinc-800">
      <table className="min-w-full divide-y divide-zinc-200 text-sm dark:divide-zinc-800">
        <thead className="bg-zinc-50 dark:bg-zinc-900">
          <tr>
            <th className={thClass}>Column</th>
            <th className={thClass}>Proposed classification</th>
            <th className={thClass}>Confidence</th>
            <th className={thClass}>Heuristic score</th>
            <th className={thClass}>LLM score</th>
            <th className={thClass}>Source</th>
            <th className={thClass}>Rationale</th>
            {canReview && <th className={thClass}>Actions</th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-zinc-200 dark:divide-zinc-800">
          {items.map((item) => (
            <ReviewQueueRow
              key={item.id}
              domain={domain}
              role={role}
              canReview={canReview}
              item={item}
              onResolved={onResolved}
            />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReviewQueueRow({
  domain,
  role,
  canReview,
  item,
  onResolved,
}: {
  domain: string;
  role: string;
  canReview: boolean;
  item: ColumnClassification;
  onResolved: (columnId: string) => void;
}) {
  const [pendingAction, setPendingAction] = useState<"approve" | "reject" | "reclassify" | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [reclassifyTarget, setReclassifyTarget] = useState<Classification>(item.classification);

  async function runAction(kind: "approve" | "reject" | "reclassify") {
    setPendingAction(kind);
    setError(null);
    try {
      if (kind === "approve") await approveColumn(domain, item.id, role);
      else if (kind === "reject") await rejectColumn(domain, item.id, role);
      else await reclassifyColumn(domain, item.id, role, reclassifyTarget);
      onResolved(item.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : `failed to ${kind} column`);
    } finally {
      setPendingAction(null);
    }
  }

  const disabled = pendingAction !== null;

  return (
    <tr>
      <td className={`${tdClass} font-mono text-xs`}>
        {item.table_name}.{item.column_name}
      </td>
      <td className={tdClass}>{item.classification}</td>
      <td className={tdClass}>{formatScore(item.confidence)}</td>
      <td className={tdClass}>{formatScore(item.heuristic_score)}</td>
      <td className={tdClass}>{formatScore(item.llm_score)}</td>
      <td className={tdClass}>{item.source}</td>
      <td className={`${tdClass} max-w-xs truncate`} title={item.llm_rationale ?? undefined}>
        {item.llm_rationale ?? "—"}
      </td>
      {canReview && (
        <td className={tdClass}>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              className={buttonClass}
              disabled={disabled}
              onClick={() => void runAction("approve")}
            >
              Approve
            </button>
            <button
              type="button"
              className={buttonClass}
              disabled={disabled}
              onClick={() => void runAction("reject")}
            >
              Reject
            </button>
            <select
              className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs dark:border-zinc-700 dark:bg-zinc-900"
              value={reclassifyTarget}
              disabled={disabled}
              onChange={(e) => setReclassifyTarget(e.target.value as Classification)}
            >
              {CLASSIFICATIONS.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
            </select>
            <button
              type="button"
              className={buttonClass}
              disabled={disabled}
              onClick={() => void runAction("reclassify")}
            >
              Reclassify
            </button>
          </div>
          {error && <p className="mt-1 text-xs text-red-600 dark:text-red-400">{error}</p>}
        </td>
      )}
    </tr>
  );
}
