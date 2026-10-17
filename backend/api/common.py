"""Row-to-model helpers shared by the W3a routers. Identifiers here are closed maps in code;
every value is a bound parameter."""

from __future__ import annotations

import base64
import binascii
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection, Row

from backend.app.errors import ApiError
from backend.match.seam import Thresholds
from contracts.models.common import ErrorCode
from contracts.models.pairs import EvidenceSnapshot, MatchDecision
from contracts.models.records import NormalizedRecord, SourceCard, SourceRecord

# What the UI prints on a source card for each source system (UX spec §3.1).
DISPLAY_LABELS: dict[str, str] = {
    "ER_FHIR": "ER FHIR",
    "CLINIC_CSV": "Clinic CSV",
    "SPECIALIST": "Specialist",
    "FRONTDESK": "FrontDesk intake",
}

DECISION_COLUMNS = (
    "d.id, d.pair_id, d.version, d.logit, d.p, d.band, d.negative_rules_fired, d.status, d.actor, d.actor_type, "
    "d.reason_code, d.note, d.decided_at, d.scorer_version, d.threshold_set_id"
)

_CURRENT_DECISION = text(
    f"SELECT {DECISION_COLUMNS}, d.raw_score, d.evidence_snapshot FROM match_decision d "
    "WHERE d.pair_id = :pair_id ORDER BY d.version DESC LIMIT 1"
)
_THRESHOLDS = text(
    "SELECT thresholds_id, c_low, c_high, platt_a, platt_b, t_low_display, t_high_display, auto_link_enabled, "
    "is_calibrated, source_run_id FROM threshold_set WHERE is_current"
)
_SOURCE_CARD = text(
    "SELECT sr.id, sr.source_system, sr.source_local_id, sr.kind, sr.payload_sha256, sr.is_constructed, sr.ingested_at, "
    "sr.raw_payload, nr.given_name, nr.family_name, nr.given_name_folded, nr.family_name_folded, nr.birth_date, nr.sex, "
    "nr.phone_e164, nr.address_line, nr.zip5 "
    "FROM source_record sr JOIN normalized_record nr ON nr.record_id = sr.id WHERE sr.id = :record_id"
)


def display_label(source_system: str) -> str:
    return DISPLAY_LABELS.get(source_system, source_system.replace("_", " ").title())


def current_thresholds(conn: Connection) -> Thresholds:
    row = conn.execute(_THRESHOLDS).one()
    return Thresholds(
        threshold_set_id=row.thresholds_id,
        c_low=row.c_low,
        c_high=row.c_high,
        platt_a=row.platt_a,
        platt_b=row.platt_b,
        t_low_display=row.t_low_display,
        t_high_display=row.t_high_display,
    )


def current_threshold_row(conn: Connection) -> Row | None:
    return conn.execute(_THRESHOLDS).one_or_none()


def current_decision_row(conn: Connection, pair_id: UUID) -> Row | None:
    return conn.execute(_CURRENT_DECISION, {"pair_id": pair_id}).one_or_none()


def decision_from_row(row: Row, snapshot: dict | None = None) -> MatchDecision:
    return MatchDecision(
        id=row.id,
        pair_id=row.pair_id,
        version=row.version,
        logit=row.logit,
        p=row.p,
        band=row.band,
        negative_rules_fired=list(row.negative_rules_fired or []),
        status=row.status,
        actor=row.actor,
        actor_type=row.actor_type,
        reason_code=row.reason_code,
        note=row.note,
        decided_at=row.decided_at,
        scorer_version=row.scorer_version,
        threshold_set_id=row.threshold_set_id,
        evidence_snapshot=None if snapshot is None else EvidenceSnapshot.model_validate(snapshot),
    )


def source_card(conn: Connection, record_id: UUID, include_raw: bool = False) -> SourceCard:
    r = conn.execute(_SOURCE_CARD, {"record_id": record_id}).one()
    record = SourceRecord(
        id=r.id,
        source_system=r.source_system,
        source_local_id=r.source_local_id,
        kind=r.kind,
        payload_sha256=r.payload_sha256,
        is_constructed=r.is_constructed,
        ingested_at=r.ingested_at,
        raw_payload=r.raw_payload if include_raw else None,
    )
    normalized = NormalizedRecord(
        record_id=r.id,
        given_name=r.given_name,
        family_name=r.family_name,
        given_name_folded=r.given_name_folded,
        family_name_folded=r.family_name_folded,
        birth_date=r.birth_date,
        sex=r.sex,
        phone_e164=r.phone_e164,
        address_line=r.address_line,
        zip5=r.zip5,
    )
    return SourceCard(record=record, normalized=normalized, display_label=display_label(r.source_system))


# Opaque keyset cursor for the review queue: (|p-0.5|, pair id) of the last item served.
def encode_cursor(distance: float, pair_id: UUID) -> str:
    raw = json.dumps({"d": distance, "id": str(pair_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[float, UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        data = json.loads(base64.urlsafe_b64decode(padded.encode()))
        return float(data["d"]), UUID(data["id"])
    except (binascii.Error, ValueError, KeyError, TypeError, AttributeError):
        raise ApiError(ErrorCode.VALIDATION_ERROR, "cursor is not valid") from None
