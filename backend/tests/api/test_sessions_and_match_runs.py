"""POST /sessions (reset) and POST /match-runs: idempotent by natural keys, events per action."""

from __future__ import annotations

from sqlalchemy import text

from backend.tests.api.conftest import API, count_events
from contracts.models.sessions import MatchRunResponse, SessionResponse


def test_reset_loads_scenario_and_writes_demo_reset(client, db_conn):
    before = count_events(db_conn, "DEMO_RESET")
    r = client.post(f"{API}/sessions", json={"scenarioId": "hero"})
    assert r.status_code == 201, r.text
    body = SessionResponse.model_validate(r.json())
    assert body.scenario_id == "hero"
    assert body.hero_provisional is True
    assert len(body.sources) >= 2
    assert r.headers["X-Request-Id"]
    assert count_events(db_conn, "DEMO_RESET") == before + 1
    row = db_conn.execute(
        text(
            "SELECT request_id, actor_type, entry_point, latency_ms FROM event_log "
            "WHERE event_type = 'DEMO_RESET' ORDER BY ts DESC LIMIT 1"
        )
    ).one()
    assert row.request_id == r.headers["X-Request-Id"]
    assert row.actor_type == "SYSTEM"
    assert row.entry_point == "API"
    assert row.latency_ms is not None and row.latency_ms >= 0


def test_reset_unknown_scenario_is_404(client):
    r = client.post(f"{API}/sessions", json={"scenarioId": "no-such-scenario"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "NOT_FOUND"


def test_reset_twice_gives_the_same_records_and_keeps_event_log(client, db_conn):
    first = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()
    events_after_first = db_conn.execute(text("SELECT count(*) FROM event_log")).scalar_one()
    second = client.post(f"{API}/sessions", json={"scenarioId": "hero"}).json()
    ids_first = sorted(s["record"]["id"] for s in first["sources"])
    ids_second = sorted(s["record"]["id"] for s in second["sources"])
    assert ids_first == ids_second
    assert second["previousSessionId"] == first["id"]
    n_records = db_conn.execute(text("SELECT count(*) FROM source_record")).scalar_one()
    assert n_records == len(ids_second)
    assert db_conn.execute(text("SELECT count(*) FROM event_log")).scalar_one() > events_after_first


def test_match_run_scores_pairs_and_writes_events(client, session, db_conn):
    r = client.post(f"{API}/match-runs")
    assert r.status_code == 201, r.text
    body = MatchRunResponse.model_validate(r.json())
    assert body.records == len(session["sources"])
    assert body.candidate_pairs >= 1
    assert 0 <= body.reduction_ratio <= 1
    assert sum(body.band_counts.values()) == body.candidate_pairs
    assert len(body.queued_pair_ids) == min(body.candidate_pairs, 50)
    assert count_events(db_conn, "MATCH_RUN_COMPLETED", run_id=str(body.run_id)) == 1
    assert count_events(db_conn, "PAIR_SCORED", run_id=str(body.run_id)) == body.candidate_pairs
    decision = db_conn.execute(
        text("SELECT version, status, actor, actor_type, evidence_snapshot FROM match_decision WHERE pair_id = :p"),
        {"p": str(body.queued_pair_ids[0])},
    ).one()
    assert (decision.version, decision.status, decision.actor_type) == (1, "PROPOSED", "SYSTEM")
    snap = decision.evidence_snapshot
    for key in (
        "features",
        "missing_flags",
        "weights",
        "intercept",
        "contributions",
        "raw_score",
        "c_low",
        "c_high",
        "negative_rules_fired",
        "scorer_version",
        "threshold_set_id",
    ):
        assert key in snap, key


def test_match_run_twice_keeps_one_decision_version_per_pair(client, session, db_conn):
    first = client.post(f"{API}/match-runs").json()
    second = client.post(f"{API}/match-runs").json()
    assert sorted(first["queuedPairIds"]) == sorted(second["queuedPairIds"])
    versions = db_conn.execute(text("SELECT max(version) FROM match_decision")).scalar_one()
    assert versions == 1
    assert db_conn.execute(text("SELECT count(*) FROM candidate_pair")).scalar_one() == second["candidatePairs"]
