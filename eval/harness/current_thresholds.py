"""The app's current threshold row, read from the migrations that create it (fork #12).

The harness and the hero export band at the operating point the product uses: the ``threshold_set`` row
with ``is_current``. CI has no database, so the row is derived by replaying the ``threshold_set``
statements of ``contracts/migrations/*.sql`` in file order (an ``INSERT`` of a current row, an
``UPDATE ... SET is_current = false``). With ``DATABASE_URL`` and ``from_database=True`` it is read
from the database instead. No cutoff is hard-coded here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "contracts" / "migrations"
_INSERT = re.compile(
    r"INSERT\s+INTO\s+threshold_set\s*\(([^)]*)\)\s*(?:VALUES\s*\(([^)]*)\)|SELECT\s+(.*?)\s+WHERE\b|SELECT\s+(.*?);)",
    re.IGNORECASE | re.DOTALL)
_UPDATE_CLEAR = re.compile(r"UPDATE\s+threshold_set\s+SET\s+is_current\s*=\s*false\b[^;]*?thresholds_id\s*=\s*'([^']+)'",
                           re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class CurrentThresholds:
    thresholds_id: str
    c_low: float
    c_high: float
    source: str

    def as_dict(self) -> dict:
        return {"thresholdsId": self.thresholds_id, "cLow": self.c_low, "cHigh": self.c_high, "source": self.source}


def _strip_comments(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def _values(text: str) -> list[str]:
    return [v.strip().strip("'") for v in text.split(",")]


def from_migrations(migrations_dir: Path = MIGRATIONS_DIR) -> CurrentThresholds:
    rows: dict[str, dict] = {}
    current: str | None = None
    for path in sorted(migrations_dir.glob("*.sql")):
        sql = _strip_comments(path.read_text())
        events = [(m.start(), "insert", m) for m in _INSERT.finditer(sql)]
        events += [(m.start(), "clear", m) for m in _UPDATE_CLEAR.finditer(sql)]
        for _, kind, m in sorted(events, key=lambda e: e[0]):
            if kind == "clear":
                if current == m.group(1):
                    current = None
                continue
            columns = [c.strip() for c in m.group(1).split(",")]
            values = _values(next(g for g in m.groups()[1:] if g))
            row = dict(zip(columns, values, strict=True))
            rows[row["thresholds_id"]] = row
            if row.get("is_current", "").lower() == "true":
                current = row["thresholds_id"]
    if current is None:
        raise ValueError(f"no current threshold_set row in {migrations_dir}")
    row = rows[current]
    return CurrentThresholds(current, float(row["c_low"]), float(row["c_high"]), f"migrations ({migrations_dir.name})")


def from_database(database_url: str) -> CurrentThresholds:
    import psycopg

    with psycopg.connect(database_url, connect_timeout=5) as conn:
        found = conn.execute("SELECT thresholds_id, c_low, c_high FROM threshold_set WHERE is_current").fetchone()
    if found is None:
        raise ValueError("no current threshold_set row in the database")
    return CurrentThresholds(found[0], float(found[1]), float(found[2]), "database")
