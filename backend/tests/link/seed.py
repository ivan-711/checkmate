"""Seed helpers: source records, pairs and decisions the way W1/W2/W3a write them."""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.tests.rule.test_bl_amox_01 import bundle, csv_allergy_row, fhir_order
from contracts.models.common import DecisionStatus, SourceKind

T0 = datetime(2026, 10, 17, 18, 0, tzinfo=UTC)
SNAPSHOT = json.dumps({"features": {}, "weights": {}, "intercept": 0.0, "contributions": [], "rawScore": 1.0,
                       "cLow": 0.0, "cHigh": 2.0, "scorerVersion": "test-scorer", "thresholdSetId": "provisional-0"})


def insert_record(conn, *, system: str, local_id: str, kind: SourceKind, raw_payload: dict, ingested_at: datetime,
                  constructed: bool = False, given: str = "Ana", family: str = "Placeholder", birth_date: str = "1985-07-03",
                  sex: str | None = "FEMALE", phone: str | None = "+15555550100", address: str | None = "100 Placeholder St",
                  zip5: str | None = "54311") -> UUID:
    rid = uuid4()
    conn.execute(text(
        "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256, is_constructed, ingested_at) "
        "VALUES (:id, :system, :local_id, :kind, CAST(:payload AS jsonb), :sha, :constructed, :ingested_at)"),
        {"id": rid, "system": system, "local_id": local_id, "kind": kind.value, "payload": json.dumps(raw_payload),
         "sha": "0" * 64, "constructed": constructed, "ingested_at": ingested_at})
    conn.execute(text(
        "INSERT INTO normalized_record (record_id, given_name, family_name, given_name_folded, family_name_folded, birth_date, "
        "sex, phone_e164, address_line, zip5) VALUES (:id, :given, :family, :gf, :ff, :dob, :sex, :phone, :address, :zip5)"),
        {"id": rid, "given": given, "family": family, "gf": given.lower(), "ff": family.lower(), "dob": birth_date,
         "sex": sex, "phone": phone, "address": address, "zip5": zip5})
    return rid


def insert_pair(conn, a: UUID, b: UUID) -> UUID:
    a, b = sorted([a, b])
    pid = uuid4()
    conn.execute(text("INSERT INTO candidate_pair (id, record_a_id, record_b_id, origin) VALUES (:id, :a, :b, 'MATCH_RUN')"),
                 {"id": pid, "a": a, "b": b})
    return pid


def insert_decision(conn, pair_id: UUID, version: int, status: DecisionStatus, *, actor: str = "registrar:Registrar A",
                    actor_type: str = "REGISTRAR", reason_code: str | None = None, band: str = "REVIEW") -> UUID:
    did = uuid4()
    conn.execute(text(
        "INSERT INTO match_decision (id, pair_id, version, logit, p, raw_score, band, evidence_snapshot, status, actor, "
        "actor_type, reason_code, scorer_version, threshold_set_id) VALUES (:id, :pair_id, :version, 1.0, 0.73, 1.0, :band, "
        "CAST(:snapshot AS jsonb), :status, :actor, :actor_type, :reason_code, 'test-scorer', 'provisional-0')"),
        {"id": did, "pair_id": pair_id, "version": version, "band": band, "snapshot": SNAPSHOT, "status": status.value,
         "actor": actor, "actor_type": actor_type, "reason_code": reason_code})
    return did


def hero_records(conn, *, order_status: str = "active", er_birth_date: str = "1985-07-03") -> tuple[UUID, UUID]:
    """Clinic CSV allergy (ingested first) and ER FHIR constructed order (ingested later).
    ``er_birth_date`` lets a test give the ER record the hero's day/month-swapped DOB."""
    clinic = insert_record(conn, system="CLINIC_CSV", local_id="CLINIC-7", kind=SourceKind.CSV_ROW,
                           raw_payload={"Id": "p", "allergies": [csv_allergy_row()], "medications": [],
                                        "encounters": [{"START": "2024-03-02", "STOP": "2024-03-02", "CODE": "185349003",
                                                        "DESCRIPTION": "Encounter for check up (procedure)", "ENCOUNTERCLASS": "ambulatory",
                                                        "ORGANIZATION": "Clinic"}]},
                           ingested_at=T0, family="Placeholder Family")
    er = insert_record(conn, system="ER_FHIR", local_id="ER-MRN-1", kind=SourceKind.FHIR_PATIENT, constructed=True,
                       raw_payload=bundle(fhir_order(status=order_status, constructed=True),
                                          {"resourceType": "Encounter", "id": "enc-1", "status": "finished", "class": {"code": "EMER"},
                                           "type": [{"coding": [{"system": "http://snomed.info/sct", "code": "50849002",
                                                                 "display": "Emergency room admission (procedure)"}]}],
                                           "period": {"start": "2026-10-17T14:00:00Z"}, "serviceProvider": {"display": "ER"}}),
                       ingested_at=T0 + timedelta(minutes=1), family="Placeholder-Family", birth_date=er_birth_date)
    return clinic, er


def linked_pair(conn, a: UUID, b: UUID) -> tuple[UUID, UUID]:
    """A PROPOSED v1 then a LINKED v2, as the review endpoint leaves them."""
    pair = insert_pair(conn, a, b)
    insert_decision(conn, pair, 1, DecisionStatus.PROPOSED, actor="system:scorer", actor_type="SYSTEM")
    decision = insert_decision(conn, pair, 2, DecisionStatus.LINKED)
    return pair, decision


# Closed map: the columns that tie a table's rows to source records. Assertions count only the rows a
# test's own records touch, because other suites (W3a's API tests) may commit rows to a shared database.
_RECORD_COLUMNS = {
    "entity_member": ("source_record_id",),
    "safety_alert": ("allergy_record_id", "order_record_id"),
    "not_a_match": ("record_a_id", "record_b_id"),
}


def rows_touching(conn, table: str, record_ids) -> int:
    where = " OR ".join(f"{column} = ANY(:ids)" for column in _RECORD_COLUMNS[table])
    return conn.execute(text(f"SELECT count(*) FROM {table} WHERE {where}"), {"ids": list(record_ids)}).scalar()
