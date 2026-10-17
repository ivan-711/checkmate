"""Source and normalized records (architecture §4)."""
from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field

from contracts.models.common import ContractModel, SourceKind


class SourceRecord(ContractModel):
    id: UUID
    source_system: str
    source_local_id: str
    kind: SourceKind
    payload_sha256: str
    is_constructed: bool = Field(default=False, description='overlay we authored; UI badge "constructed scenario"')
    ingested_at: datetime
    raw_payload: dict | None = Field(default=None, description="immutable; included only in the evidence view")


class NormalizedRecord(ContractModel):
    record_id: UUID
    given_name: str | None = None
    family_name: str | None = None
    given_name_folded: str | None = None
    family_name_folded: str | None = None
    birth_date: date | None = None
    sex: str | None = None
    phone_e164: str | None = None
    address_line: str | None = None
    zip5: str | None = None


class SourceCard(ContractModel):
    """What the UI renders as one source card (UX spec §3.1)."""

    record: SourceRecord
    normalized: NormalizedRecord
    display_label: str = Field(description='e.g. "ER FHIR" or "Clinic CSV"')
