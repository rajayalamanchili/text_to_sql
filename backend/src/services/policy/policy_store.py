"""Policy artifact store: versioned YAML read/write + manifest-based
active-version resolution (research.md §6, data-model.md#PolicyArtifact,
FR-006/FR-007).

Layout per domain, rooted at `DomainConfig.policy_dir`
(`policies/<domain>/`, git-versioned per `tech-stack.md`):

    policies/<domain>/manifest.yaml        # {"active_version": <int>}
    policies/<domain>/<version>/policy.yaml

The manifest pointer only ever advances forward on publish — there is no
rollback action in Milestone 1 (spec.md Clarifications, 2026-07-28); "the
active policy artifact" (FR-007) always means the most recently published
version, resolved via this single manifest, never by comparing version
numbers some other way.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from src.config.domains import DomainConfig
from src.models.policy_artifact import PolicyArtifact, PolicyTable

_MANIFEST_FILENAME = "manifest.yaml"
_ARTIFACT_FILENAME = "policy.yaml"


class PolicyStore:
    """Reads/writes one domain's versioned policy artifacts."""

    def __init__(self, domain_config: DomainConfig) -> None:
        self._domain = domain_config.name
        self._policy_dir = domain_config.policy_dir
        self._manifest_path = self._policy_dir / _MANIFEST_FILENAME

    def _version_dir(self, version: int) -> Path:
        return self._policy_dir / str(version)

    def _artifact_path(self, version: int) -> Path:
        return self._version_dir(version) / _ARTIFACT_FILENAME

    def active_version(self) -> int | None:
        """The manifest's active-version pointer, or `None` if this
        domain has never had a policy published."""
        if not self._manifest_path.exists():
            return None
        manifest = yaml.safe_load(self._manifest_path.read_text()) or {}
        return manifest.get("active_version")

    def get_active(self) -> PolicyArtifact | None:
        """The currently active `PolicyArtifact` for this domain, or
        `None` if none has ever been published — callers MUST treat
        `None` as "nothing is allowed" (FR-009), not as an error to retry
        past."""
        version = self.active_version()
        if version is None:
            return None
        return self.get_version(version)

    def get_version(self, version: int) -> PolicyArtifact | None:
        """One specific published version, or `None` if it doesn't exist
        on disk."""
        path = self._artifact_path(version)
        if not path.exists():
            return None
        raw = yaml.safe_load(path.read_text())
        return PolicyArtifact.model_validate(raw)

    def publish(self, tables: list[PolicyTable], *, approved_by: str) -> PolicyArtifact:
        """Publish a new version built from `tables`, incrementing the
        domain's version monotonically (FR-006) and advancing the
        manifest pointer forward — never rolling back (spec.md
        Clarifications, 2026-07-28)."""
        next_version = (self.active_version() or 0) + 1
        artifact = PolicyArtifact(
            domain=self._domain,
            version=next_version,
            tables=tables,
            approved_by=approved_by,
            approved_at=datetime.now(UTC),
        )
        self._version_dir(next_version).mkdir(parents=True, exist_ok=True)
        self._artifact_path(next_version).write_text(
            yaml.safe_dump(artifact.model_dump(mode="json"), sort_keys=False)
        )
        self._manifest_path.write_text(
            yaml.safe_dump({"active_version": next_version}, sort_keys=False)
        )
        return artifact
