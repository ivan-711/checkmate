import random
from datetime import date

from backend.ingest import corruptor as c
from backend.ingest.normalize import Identity, parse_date
from backend.tests.ingest.conftest import PATIENT_A, PATIENT_B

SPANISH = Identity(given="María", middle="José", family="García López", birth_date="1990-03-07", sex="female",
                   phone="555-123-4567", address_line="857 Kling Arcade", city="Worcester", state="MA", postal_code="01604",
                   language="es", mother_maiden="Isabela López")
ENGLISH = Identity(given="Robert", family="Smith", birth_date="1985-11-02", sex="male", phone="555-987-6543",
                   address_line="1 Main St", city="Boston", state="MA", postal_code="02118", language="en-US")


def rng() -> random.Random:
    return random.Random(7)


def test_each_core_edit_changes_a_value_and_labels_it():
    for family in c.CORE_TRUE_MATCH:
        identity = SPANISH if family in ("S1", "S3", "S5", "S6") else ENGLISH
        outcome = c.EDITS[family](identity, rng())
        assert outcome is not None, family
        changed, edit = outcome
        assert edit.family == family and changed != identity
        assert edit.before != edit.after


def test_specific_edit_shapes():
    assert c.edit_t3(ENGLISH, rng())[0].given in c.GENERATOR_NICKNAMES["Robert"]
    assert c.edit_d1(Identity(birth_date="1990-03-07"), rng())[0].birth_date == "1990-07-03"
    assert c.edit_d3(ENGLISH, rng())[0].birth_date[:4] in ("1984", "1986")
    assert c.edit_l3(ENGLISH, rng())[0].phone is None
    moved = c.edit_l7(ENGLISH, rng())[0]
    assert (moved.address_line, moved.city, moved.postal_code) == (None, None, None)
    assert c.edit_s1(SPANISH, rng())[0].given == "Maria"
    assert c.edit_s3(SPANISH, rng())[0].family == "García"
    assert c.edit_s5(SPANISH, rng())[0].family in ("García-López", "GarcíaLópez")
    assert c.edit_s6(SPANISH, rng())[0].given == "Ma."
    t1 = c.edit_t1(ENGLISH, rng())[0].family
    assert t1 != "Smith" and abs(len(t1) - len("Smith")) <= 1
    _, summary = c.edit_c1(ENGLISH, rng())
    assert summary.family == "C1" and len(summary.field.split("+")) >= 2


def test_no_op_edits_are_skipped_not_counted():
    assert c.edit_t3(Identity(given="Zebediah"), rng()) is None  # not in the nickname table
    assert c.edit_d1(Identity(birth_date="1990-03-17"), rng()) is None  # day cannot be a month
    assert c.edit_d1(Identity(birth_date="1990-03-03"), rng()) is None  # swap is identity
    assert c.edit_l3(Identity(), rng()) is None
    assert c.edit_s1(ENGLISH, rng()) is None  # nothing accented
    assert c.edit_s3(ENGLISH, rng()) is None  # one surname
    assert c.edit_s6(ENGLISH, rng()) is None


def test_two_surname_families_only_for_spanish_entities():
    families = {c.sample_family(random.Random(i), spanish=False) for i in range(300)}
    assert not families & c.TWO_SURNAME_FAMILIES
    assert c.TWO_SURNAME_FAMILIES <= {c.sample_family(random.Random(i), spanish=True) for i in range(300)}


def test_spanish_base_identity_adds_the_maternal_surname_keeping_particles():
    base = Identity(family="Solano", language="es", mother_maiden="Isabela97 de Anda905")
    assert c.spanish_base_identity(base).family == "Solano de Anda"
    assert c.spanish_base_identity(ENGLISH).family == "Smith"  # English speakers keep one surname
    assert c.maternal_surname("Isabela") is None


def test_grafts_produce_siblings_and_parent_child():
    sibling = c.graft(ENGLISH, SPANISH, "N1", rng())
    assert (sibling.family, sibling.address_line, sibling.phone) == ("Smith", "1 Main St", "555-987-6543")
    assert sibling.given != "Robert"
    assert 1 <= abs(parse_date(sibling.birth_date).year - 1985) <= c.SIBLING_MAX_YEAR_GAP
    child = c.graft(ENGLISH, SPANISH, "N3", rng())
    assert (child.given, child.family, child.address_line) == ("Robert", "Smith", "1 Main St")
    assert abs(parse_date(child.birth_date).year - 1985) >= c.PARENT_CHILD_MIN_YEARS


def test_graft_group_shares_one_component_and_one_split():
    ids = [f"p{i}" for i in range(60)]
    grafts = [c.GraftSpec("N1", "p1", "p2"), c.GraftSpec("N3", "p2", "p3")]
    comp = c.components(ids, grafts)
    assert comp["p1"] == comp["p2"] == comp["p3"] == "p1" and comp["p4"] == "p4"
    splits = c.assign_splits(comp, {k: "other" for k in comp.values()})
    assert len(splits["p1"]["members"]) == 3
    partitions = {s["partition"] for s in splits.values()}
    assert partitions == {"showcase", "development", "test"}
    assert sum(1 for s in splits.values() if s["partition"] == "showcase") == c.SHOWCASE_POOL_SIZE
    assert all(s["fold"] is not None for s in splits.values() if s["partition"] == "development")


def test_heldout_families_are_seed_chosen_and_stratified():
    drawn = c.draw_heldout_families(20261017)
    assert drawn == c.draw_heldout_families(20261017) and len(set(drawn)) == c.HELDOUT_COUNT
    assert set(drawn) <= set(c.P1_FAMILIES)
    assert set(drawn) & set(c.HELDOUT_SPANISH_STRATUM)
    assert set(drawn) & set(c.HELDOUT_NEGATIVE_STRATUM)
    assert set(drawn) & set(c.HELDOUT_DOB_ADDRESS_STRATUM)
    assert drawn != c.draw_heldout_families(1)


def test_build_corpus_is_deterministic_for_a_seed(bundles, csv_patients, tmp_path):
    first = c.write_outputs(c.build_corpus(42, bundles, csv_patients), tmp_path / "a")
    second = c.write_outputs(c.build_corpus(42, bundles, csv_patients), tmp_path / "b")
    assert first.sha256 == second.sha256
    other = c.write_outputs(c.build_corpus(43, bundles, csv_patients), tmp_path / "c")
    assert other.sha256["truth"] != first.sha256["truth"]
    ids = [str(r.draft.id) for r in first.records]
    assert len(ids) == len(set(ids))
    assert {r.synthea_id for r in first.records} == {PATIENT_A, PATIENT_B}
    assert all(p["label"] in (c.LABEL_SAME, c.LABEL_NOT_SAME) for p in first.pairs)
    assert first.run["heldout_families"] == c.draw_heldout_families(42)
    assert (tmp_path / "a" / "truth.csv").read_text().splitlines()[0].startswith("entity_id,record_id,source_system,synthea_patient_id")


def test_spanish_entity_gets_the_compound_surname_in_its_base_records(bundles, csv_patients):
    entities = c.build_entities(bundles, csv_patients)
    assert entities[PATIENT_A].identity.family == "Núñez-García de Anda"
    assert entities[PATIENT_B].identity.family == "Smith"


def test_shift_years_handles_leap_day():
    assert c._shift_years(date(2000, 2, 29), 1) == date(2001, 2, 28)
