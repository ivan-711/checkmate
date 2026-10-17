"""Download the Synthea Nov 2021 sample (555 patients): FHIR R4 and CSV zips.

``uv run python data/download.py [--dest data/raw]``

Sample page: https://synthetichealth.github.io/synthea/ ("No Cost, No Restrictions"); files live under
https://synthetichealth.github.io/synthea-sample-data/downloads/ (listing verified 2026-10-17). Each
file's SHA-256 and size go to data/HASHES.json; archives and extracted data stay under the
gitignored data/raw. Raw data is never committed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
import zipfile
from pathlib import Path

BASE_URL = "https://synthetichealth.github.io/synthea-sample-data/downloads/"
FILES = {
    "synthea_sample_data_fhir_r4_nov2021.zip": 94_887_125,
    "synthea_sample_data_csv_nov2021.zip": 58_771_261,
}
HASHES_PATH = Path(__file__).resolve().parent / "HASHES.json"
CHUNK = 1 << 20


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(name: str, dest: Path) -> Path:
    target = dest / name
    if target.exists() and target.stat().st_size == FILES[name]:
        return target
    dest.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(BASE_URL + name) as resp, target.open("wb") as out:
        for chunk in iter(lambda: resp.read(CHUNK), b""):
            out.write(chunk)
    if target.stat().st_size != FILES[name]:
        raise SystemExit(f"{name}: got {target.stat().st_size} bytes, expected {FILES[name]}")
    return target


def extract(archive: Path, dest: Path) -> int:
    """Safe extraction (absolute or '..' members refused), skipped when its marker says it is done."""
    marker = dest / f".extracted-{archive.name}"
    if marker.exists():
        return int(marker.read_text() or 0)
    count = 0
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            name = member.filename
            if name.startswith("/") or ".." in Path(name).parts:
                raise SystemExit(f"refusing unsafe archive member {name!r}")
            zf.extract(member, dest)
            count += not member.is_dir()
    marker.write_text(str(count))
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dest", type=Path, default=Path("data/raw"))
    args = parser.parse_args(argv)
    hashes = json.loads(HASHES_PATH.read_text()) if HASHES_PATH.exists() else {}
    for name in FILES:
        archive = download(name, args.dest / "zips")
        digest = sha256_of(archive)
        recorded = hashes.get(name, {}).get("sha256")
        if recorded and recorded != digest:
            raise SystemExit(f"{name}: sha256 {digest} differs from HASHES.json {recorded}")
        hashes[name] = {"url": BASE_URL + name, "bytes": archive.stat().st_size, "sha256": digest}
        files = extract(archive, args.dest)
        print(f"{name}: sha256={digest} files={files}")
    HASHES_PATH.write_text(json.dumps(hashes, indent=2) + "\n")
    print(f"hashes written to {HASHES_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
