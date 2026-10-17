"""R3a round 3 reviewer tests for GET /events on lane/w3a @ e9a8e45.

Both are expected to FAIL on e9a8e45 and document should-fix findings:
- camel_keys rewrites data-valued payload keys (a UUID key is title-cased, a mixed-case key is folded) and
  silently drops a value when two keys camelCase to the same name. Only snake_case identifiers should change.
- `since` accepts a bare number (read as a Unix time) and a date without a time, where the contract declares
  `format: date-time`; schemathesis reports "API accepted schema-violating request".
"""

from __future__ import annotations

import pytest

from backend.api.events import camel_keys
from backend.tests.api.conftest import API

RECORD_ID = "d15faba8-6c93-4bbf-bc28-c4aa700f4747"


def test_camel_keys_changes_snake_case_identifiers_only():
    served = camel_keys(
        {
            "band_counts": {"AUTO_LINK": 1},
            "by_record": {RECORD_ID: "REVIEW"},
            "HTTPStatus": 503,
            "alertId": "already camel",
            "deep": [{"inner_key": 1}],
        }
    )
    assert served["bandCounts"] == {"AUTO_LINK": 1}
    assert served["deep"] == [{"innerKey": 1}]
    assert served["alertId"] == "already camel"
    assert served["byRecord"] == {RECORD_ID: "REVIEW"}, "a UUID key must still equal the id it names"
    assert served["HTTPStatus"] == 503, "a key that is not snake_case is served as stored"


def test_camel_keys_never_drops_a_value_when_two_keys_collide():
    served = camel_keys({"raw_score": 1.0, "rawScore": 2.0})
    assert sorted(served.values()) == [1.0, 2.0], served


@pytest.mark.parametrize("since", ["0.5", "1700000000", "2026-10-17"])
def test_since_that_is_not_a_date_time_is_a_422(client, since):
    r = client.get(f"{API}/events", params={"since": since})
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
