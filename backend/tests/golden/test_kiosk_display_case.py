"""The golden record after a registrar attaches the kiosk check-in keeps the sources' display spelling.

The intake record is the newest member, so it wins every "most recent" tie-break; its display
columns must therefore hold the patient's typed spelling, as ingest's do, never core's folded form.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from backend.chart_store.writes import normalized_row as intake_row
from backend.golden.survivorship import MemberDemographics, golden_demographics
from backend.ingest.normalize import Identity
from backend.ingest.normalize import normalized_row as ingest_row
from backend.tests.policy.factories import propose_args
from contracts.models.policy import Sex

T0 = datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
HERO = {"given_name": "Sofia", "family_name": "Mesa-López", "birth_date": "1964-05-16", "sex": Sex.FEMALE}
ADDRESS = "899 Sawayn Trafficway"


def member(system: str, minutes: int, row: dict) -> MemberDemographics:
    return MemberDemographics(
        source_system=system,
        source_local_id=f"{system}-1",
        ingested_at=T0 + timedelta(minutes=minutes),
        given_name=row["given_name"],
        family_name=row["family_name"],
        birth_date=row["birth_date"],
        sex=row["sex"],
        phone_e164=row["phone_e164"],
        address_line=row["address_line"],
        zip5=row["zip5"],
    )


def test_attached_kiosk_check_in_keeps_display_casing_in_the_golden_record():
    er = ingest_row(Identity(given="Sofia", family="Mesa-López", birth_date="1964-05-16", sex="female"))
    clinic = ingest_row(Identity(given="Sofia", family="Mesa Lopez", birth_date="05/16/1964", sex="F"))
    kiosk = intake_row(propose_args(**HERO, phone="5557573688", address_line=ADDRESS))
    golden = {
        f.field: f.value
        for f in golden_demographics(
            [member("ER_FHIR", 0, er), member("CLINIC_CSV", 1, clinic), member("FRONTDESK_INTAKE", 2, kiosk)]
        )
    }
    assert golden["givenName"] == "Sofia"
    assert golden["familyName"] == "Mesa-López"
    assert golden["sex"] == "FEMALE"
    assert golden["address"] == ADDRESS


def test_intake_row_reads_back_exactly_as_the_folded_row_did():
    """Only the display columns change: the gate and scorer re-normalize to the same record."""
    from backend.core.normalize import coerce_normalized, normalize_record

    args = propose_args(**HERO, phone="5557573688", address_line=ADDRESS, postal_code="02134")
    folded = normalize_record(
        {
            "given_name": args.given_name,
            "family_name": args.family_name,
            "birth_date": args.birth_date,
            "sex": args.sex.value,
            "phone": args.phone,
            "address_line": args.address_line,
            "zip": args.postal_code,
        }
    ).to_row_dict()
    assert coerce_normalized(intake_row(args)) == coerce_normalized(folded)
