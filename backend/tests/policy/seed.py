"""Seed one near-duplicate pair and an intake session the way ingest and the API write them."""

from __future__ import annotations

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from backend.core.api import CORE
from backend.core.normalize import normalize_record
from contracts.models.common import SourceKind
from contracts.version import TOOL_SCHEMA_VERSION

ER_DEMOGRAPHICS = {
    "given_name": "Maria Jose",
    "family_name": "Gonzalez Rivera",
    "birth_date": "1985-07-03",
    "sex": "F",
    "phone": "+15550100100",
    "address_line": "100 Main St",
    "zip": "54311",
}
# Clinic copy with the hero's day/month swap and dropped accents: lands in REVIEW by construction.
CLINIC_DEMOGRAPHICS = {**ER_DEMOGRAPHICS, "given_name": "María José", "birth_date": "1985-03-07"}
UNRELATED_DEMOGRAPHICS = {
    "given_name": "Theodore",
    "family_name": "Blackwood",
    "birth_date": "1950-01-15",
    "sex": "M",
    "phone": "+15559990000",
    "address_line": "9 Elm Rd",
    "zip": "10001",
}


def insert_record(conn, *, system: str, local_id: str, kind: SourceKind, demographics: dict) -> UUID:
    rid = uuid4()
    conn.execute(
        text(
            "INSERT INTO source_record (id, source_system, source_local_id, kind, raw_payload, payload_sha256) "
            "VALUES (:id, :system, :local_id, :kind, CAST(:payload AS jsonb), :sha)"
        ),
        {
            "id": rid,
            "system": system,
            "local_id": local_id,
            "kind": kind.value,
            "payload": json.dumps(demographics),
            "sha": "0" * 64,
        },
    )
    row = {**normalize_record(demographics).to_row_dict(), "record_id": rid}
    conn.execute(
        text(
            "INSERT INTO normalized_record (record_id, given_name, family_name, given_name_folded, family_name_folded, "
            "birth_date, birth_year, birth_month, birth_day, sex, phone_e164, address_line, zip5) VALUES (:record_id, "
            ":given_name, :family_name, :given_name_folded, :family_name_folded, :birth_date, :birth_year, "
            ":birth_month, :birth_day, :sex, :phone_e164, :address_line, :zip5)"
        ),
        row,
    )
    for key in CORE.block_keys(row):
        conn.execute(
            text("INSERT INTO block_key (key_type, key_value, record_id) VALUES (:t, :v, :r) ON CONFLICT DO NOTHING"),
            {"t": key.key_type, "v": key.key_value, "r": rid},
        )
    return rid


def near_duplicates(conn) -> tuple[UUID, UUID]:
    er = insert_record(
        conn, system="ER_FHIR", local_id="ER-1", kind=SourceKind.FHIR_PATIENT, demographics=ER_DEMOGRAPHICS
    )
    clinic = insert_record(
        conn, system="CLINIC_CSV", local_id="CLINIC-1", kind=SourceKind.CSV_ROW, demographics=CLINIC_DEMOGRAPHICS
    )
    return er, clinic


def insert_session(conn) -> UUID:
    sid = uuid4()
    conn.execute(
        text(
            "INSERT INTO intake_session (id, language, agent_mode, prompt_version, tool_schema_version) "
            "VALUES (:id, 'ES', 'REPLAY', 'test-prompt/1', :tsv)"
        ),
        {"id": sid, "tsv": TOOL_SCHEMA_VERSION},
    )
    return sid


def insert_tool_call(conn, session_id: UUID, evidence_ids: list[UUID], step_index: int = 0) -> UUID:
    tid = uuid4()
    conn.execute(
        text(
            "INSERT INTO agent_tool_call (id, session_id, turn_index, step_index, tool_name, args_sha256, gate_outcome, "
            "evidence_ids, evidence_snapshot, effect_status, policy_version) VALUES (:id, :sid, 0, :step, "
            "'search_patients', :sha, 'ALLOW', CAST(:ids AS uuid[]), '{}', 'NONE', 'frontdesk-gate/1')"
        ),
        {"id": tid, "sid": session_id, "step": step_index, "sha": "f" * 64, "ids": [str(i) for i in evidence_ids]},
    )
    return tid
