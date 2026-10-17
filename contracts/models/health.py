"""GET /health."""
from __future__ import annotations

from enum import StrEnum

from contracts.models.common import ContractModel


class DependencyStatus(StrEnum):
    UP = "UP"
    DOWN = "DOWN"
    REPLAY = "REPLAY"


class AgentStatus(StrEnum):
    LIVE = "LIVE"
    REPLAY = "REPLAY"
    DOWN = "DOWN"


class HealthVersions(ContractModel):
    contract_version: str
    policy_version: str
    tool_schema_version: str
    scorer_version: str | None = None
    threshold_set_id: str | None = None
    git_sha: str | None = None


class Health(ContractModel):
    db: DependencyStatus
    gemini: DependencyStatus
    modal: DependencyStatus
    mirror: DependencyStatus
    agent: AgentStatus
    versions: HealthVersions
