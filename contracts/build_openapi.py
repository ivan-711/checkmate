"""Write or check ``contracts/openapi.json`` from the stub app.

``python -m contracts.build_openapi``          writes the snapshot
``python -m contracts.build_openapi --check``  exits 1 if the snapshot is stale
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from contracts.api_spec import build_app

SNAPSHOT = Path(__file__).parent / "openapi.json"
FROZEN_PATHS = (
    "/api/v1/health", "/api/v1/sessions", "/api/v1/match-runs", "/api/v1/candidate-pairs",
    "/api/v1/candidate-pairs/{pair_id}", "/api/v1/candidate-pairs/{pair_id}/reviews",
    "/api/v1/entities/{entity_id}", "/api/v1/candidate-pairs/{pair_id}/what-ifs",
    "/api/v1/intake-sessions", "/api/v1/intake-sessions/{session_id}/turns",
    "/api/v1/intake-sessions/{session_id}", "/api/v1/metrics/tiles",
)


def render() -> str:
    spec = build_app().openapi()
    missing = [path for path in FROZEN_PATHS if path not in spec["paths"]]
    if missing:
        raise SystemExit(f"frozen paths missing from the spec: {missing}")
    return json.dumps(spec, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str]) -> int:
    rendered = render()
    if "--check" in argv:
        if not SNAPSHOT.exists() or SNAPSHOT.read_text() != rendered:
            print("openapi.json is stale: run `python -m contracts.build_openapi`", file=sys.stderr)
            return 1
        print("openapi.json is current")
        return 0
    SNAPSHOT.write_text(rendered)
    print(f"wrote {SNAPSHOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
