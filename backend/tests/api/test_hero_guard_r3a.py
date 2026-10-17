"""R3a reviewer tests for PR #17 (lane W3a, hero guard) at 2635f54. Both are expected to FAIL there:

- The corpus cache key hashes every file under the hero directory, so a file the loader never reads
  (a .DS_Store that Finder writes when the folder is opened, an editor swap file) forces a cold corpus
  rebuild on the next reset: 17 s on W5's real export, in front of a judge.
- Four more shapes of an unusable export still escape the guard as a 500 logged only by exception class,
  instead of the refusal 404 every other unusable export gets.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text

from backend.scenarios import loader
from backend.tests.api.conftest import API


def test_a_file_the_loader_never_reads_does_not_change_the_cache_key(hero_corpus):
    before = loader.hero_fingerprint(hero_corpus.hero_dir)
    (hero_corpus.hero_dir / ".DS_Store").write_bytes(b"\x00\x00\x00\x01Bud1")
    (hero_corpus.hero_dir / "fhir" / ".hero_er.json.swp").write_bytes(b"swap")
    assert loader.hero_fingerprint(hero_corpus.hero_dir) == before


def _er_bundle(hero_dir):
    return hero_dir / "fhir" / "hero_er.json"


def _entry_not_an_object(hero_dir):
    bundle = json.loads(_er_bundle(hero_dir).read_text())
    bundle["entry"].append("x")
    _er_bundle(hero_dir).write_text(json.dumps(bundle))


def _constructed_patient_without_id(hero_dir):
    bundle = json.loads(_er_bundle(hero_dir).read_text())
    for entry in bundle["entry"]:
        if entry["resource"]["resourceType"] == "Patient":
            entry["resource"].pop("id", None)
    _er_bundle(hero_dir).write_text(json.dumps(bundle))


def _allergies_csv_not_utf8(hero_dir):
    path = hero_dir / "csv" / "allergies.csv"
    path.write_bytes(path.read_bytes() + b"\xff\xfe,bad\n")


def _hero_json_is_a_directory(hero_dir):
    (hero_dir / "hero.json").unlink()
    (hero_dir / "hero.json").mkdir()


BREAKAGES = {
    "bundle entry not an object": _entry_not_an_object,
    "constructed Patient without id": _constructed_patient_without_id,
    "allergies.csv not UTF-8": _allergies_csv_not_utf8,
    "hero.json is a directory": _hero_json_is_a_directory,
}


@pytest.mark.parametrize("case", sorted(BREAKAGES))
def test_every_unusable_export_is_refused_like_a_missing_hero(client, hero_corpus, db_conn, case):
    assert client.post(f"{API}/sessions", json={"scenarioId": "hero"}).status_code == 201
    records = db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()
    BREAKAGES[case](hero_corpus.hero_dir)
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 404, r.text
    assert r.json()["error"]["code"] == "NOT_FOUND"
    assert r.json()["error"]["message"].startswith("hero scenario not found")
    assert db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one() == records
