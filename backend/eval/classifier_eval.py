#!/usr/bin/env python3
"""Classifier precision/recall eval (spec.md Success Criteria, T028-T030).

Usage (per quickstart.md — run from the repo root):

    python backend/eval/classifier_eval.py --domain healthcare
    python backend/eval/classifier_eval.py --domain fintech
    python backend/eval/classifier_eval.py              # all domains with a ground truth file

Runs the real classification pipeline (`run_classification`, T024) —
enumerate -> heuristic -> confidence gate -> LLM (via
`build_default_llm_client`, real Anthropic if a credential is
configured, `NullLLMClient` otherwise) -> combine — against the given
domain's live database, then scores the resulting
`ColumnClassification.classification` values against the hand-labeled
ground truth in `eval/ground_truth/<domain>.csv` (T028/T029).

Gate: `pii_direct` precision AND recall, evaluated **per domain**
(quickstart.md: "precision/recall on pii_direct >= 0.85 each, per
domain"), must both be >= 0.85 (spec.md Success Criteria — false
negatives on direct identifiers are the highest-consequence error).
Exits non-zero if any evaluated domain fails, so CI (T066) blocks merge
on regression, per Constitution Principle VI.

Domain-agnostic by construction (Constitution Principle IV): domains are
discovered via `config.domains.list_domains()`/`get_domain()`, and only
those with a `ground_truth/<domain>.csv` file are evaluated — adding a
third domain needs a new CSV, no code change. A domain whose database
isn't reachable is skipped (printed, not failed) — an environment gap,
not a classifier failure, mirroring
`tests/integration/conftest.py`'s existing convention.

Predictions are computed with a throwaway in-memory `ClassificationStore`
(`_CollectingStore`) — this script never writes to a domain's real
`column_classifications` or `audit_log` tables; only enumeration's own
read-only aggregate queries (`count(*)`/`count(DISTINCT ...)`) touch the
database.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

# Allow `python backend/eval/classifier_eval.py` from the repo root
# (quickstart.md) as well as running via the backend package — `src` is
# a sibling of this script's directory, not its parent's parent.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from src.config.domains import (  # noqa: E402
    DomainConfig,
    UnknownDomainError,
    get_domain,
    list_domains,
)
from src.graph.classification_graph import run_classification  # noqa: E402
from src.models.column_classification import Classification, ColumnClassification  # noqa: E402
from src.services.classification.anthropic_client import build_default_llm_client  # noqa: E402

GROUND_TRUTH_DIR = Path(__file__).resolve().parent / "ground_truth"

PII_DIRECT_PRECISION_TARGET = 0.85
PII_DIRECT_RECALL_TARGET = 0.85
GATED_CLASSIFICATION = Classification.PII_DIRECT


class _CollectingStore:
    """No-op `ClassificationStore` (classification_graph.py) — collects
    predictions in memory instead of persisting, so running this eval
    never mutates a domain's real tables."""

    def __init__(self) -> None:
        self.records: list[ColumnClassification] = []

    async def save(self, record: ColumnClassification) -> None:
        self.records.append(record)


@dataclass
class GroundTruthRow:
    table_name: str
    column_name: str
    expected_classification: Classification


def load_ground_truth(path: Path) -> list[GroundTruthRow]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [
            GroundTruthRow(
                table_name=row["table_name"],
                column_name=row["column_name"],
                expected_classification=Classification(row["expected_classification"]),
            )
            for row in reader
        ]


def _is_database_reachable(database_url: str | None) -> bool:
    if not database_url:
        return False
    try:
        with psycopg.connect(database_url, connect_timeout=3):
            return True
    except psycopg.OperationalError:
        return False


async def classify_domain(domain: DomainConfig) -> dict[tuple[str, str], Classification]:
    """Run the real classification pipeline for `domain` and return
    predictions keyed by (table_name, column_name)."""
    store = _CollectingStore()
    with psycopg.connect(domain.database_url) as conn:
        await run_classification(
            domain=domain.name,
            conn=conn,
            llm_client=build_default_llm_client(),
            store=store,
        )
    return {(r.table_name, r.column_name): r.classification for r in store.records}


@dataclass
class CategoryMetrics:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0

    @property
    def precision(self) -> float | None:
        denominator = self.true_positives + self.false_positives
        return self.true_positives / denominator if denominator else None

    @property
    def recall(self) -> float | None:
        denominator = self.true_positives + self.false_negatives
        return self.true_positives / denominator if denominator else None


def score(
    ground_truth: list[GroundTruthRow],
    predictions: dict[tuple[str, str], Classification],
) -> tuple[dict[Classification, CategoryMetrics], list[str]]:
    """Score `predictions` against `ground_truth`, per classification
    category. Returns (metrics-by-category, missing-column-labels)."""
    metrics: dict[Classification, CategoryMetrics] = {c: CategoryMetrics() for c in Classification}
    missing: list[str] = []
    for row in ground_truth:
        predicted = predictions.get((row.table_name, row.column_name))
        if predicted is None:
            missing.append(f"{row.table_name}.{row.column_name}")
            continue
        if predicted == row.expected_classification:
            metrics[predicted].true_positives += 1
        else:
            metrics[predicted].false_positives += 1
            metrics[row.expected_classification].false_negatives += 1
    return metrics, missing


def _format_rate(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "n/a"


def _print_report(domain_name: str, metrics: dict[Classification, CategoryMetrics]) -> bool:
    """Print the per-category breakdown and the pii_direct gate line for
    one domain. Returns whether that domain passed the gate."""
    for classification, m in metrics.items():
        print(
            f"  {classification.value:<20} precision={_format_rate(m.precision):>5} "
            f"recall={_format_rate(m.recall):>5} "
            f"(tp={m.true_positives} fp={m.false_positives} fn={m.false_negatives})"
        )

    gated = metrics[GATED_CLASSIFICATION]
    passed = (
        gated.precision is not None
        and gated.recall is not None
        and gated.precision >= PII_DIRECT_PRECISION_TARGET
        and gated.recall >= PII_DIRECT_RECALL_TARGET
    )
    print(
        f"[{domain_name}] {GATED_CLASSIFICATION.value} gate: "
        f"precision={_format_rate(gated.precision)} (target >= {PII_DIRECT_PRECISION_TARGET}), "
        f"recall={_format_rate(gated.recall)} (target >= {PII_DIRECT_RECALL_TARGET}) "
        f"-> {'PASS' if passed else 'FAIL'}"
    )
    return passed


async def evaluate_domain(domain: DomainConfig, ground_truth_path: Path) -> bool | None:
    """Evaluate one domain. Returns True/False for pass/fail, or None if
    skipped because its database isn't reachable."""
    if not _is_database_reachable(domain.database_url):
        print(
            f"[skip] {domain.name}: {domain.name.upper()}_DATABASE_URL not set/unreachable "
            "— start docker compose to evaluate this domain"
        )
        return None

    ground_truth = load_ground_truth(ground_truth_path)
    predictions = await classify_domain(domain)
    metrics, missing = score(ground_truth, predictions)
    if missing:
        print(
            f"[warn] {domain.name}: {len(missing)} ground-truth column(s) not found in the "
            f"current schema/classification output: {', '.join(missing)}"
        )

    print(f"\n=== {domain.name} ===")
    return _print_report(domain.name, metrics)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--domain",
        help=(
            "Evaluate only this domain (default: every domain with a "
            "ground_truth/<domain>.csv file)"
        ),
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    if args.domain:
        try:
            domain_config = get_domain(args.domain)
        except UnknownDomainError as exc:
            print(f"error: {exc}")
            return 1
        ground_truth_path = GROUND_TRUTH_DIR / f"{args.domain}.csv"
        if not ground_truth_path.is_file():
            print(f"error: no ground truth file at {ground_truth_path}")
            return 1
        domains_with_ground_truth = [(domain_config, ground_truth_path)]
    else:
        domains_with_ground_truth = [
            (domain, GROUND_TRUTH_DIR / f"{domain.name}.csv")
            for domain in list_domains()
            if (GROUND_TRUTH_DIR / f"{domain.name}.csv").is_file()
        ]

    if not domains_with_ground_truth:
        print(f"No ground truth files found under {GROUND_TRUTH_DIR} — nothing to evaluate.")
        return 0

    results = [
        await evaluate_domain(domain, ground_truth_path)
        for domain, ground_truth_path in domains_with_ground_truth
    ]

    evaluated = [r for r in results if r is not None]
    if not evaluated:
        print("\nNo domain database was reachable — eval skipped (environment gap, not a failure).")
        return 0

    return 0 if all(evaluated) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
