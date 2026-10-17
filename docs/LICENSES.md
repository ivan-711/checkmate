# License inventory

Author: Gojo (docs) · 2026-10-17

Every third-party package this repository installs, read from its lock file. Licenses are the SPDX expression (or, where a package publishes none, the license field and classifiers) in the PyPI metadata for the exact pinned version. Regenerate this list whenever a lock file changes.

The project's own code license is not set yet.

## Python: `uv.lock`

Runtime packages are reached from `[project].dependencies` in `pyproject.toml`; dev-only packages are reached only from `[dependency-groups].dev`.

| Package | Version | License | Scope |
|---|---|---|---|
| annotated-doc | 0.0.5 | MIT | runtime |
| annotated-types | 0.8.0 | MIT | runtime |
| anyio | 4.15.1 | MIT | runtime |
| attrs | 26.1.0 | MIT | dev |
| certifi | 2026.7.22 | MPL-2.0 | dev |
| click | 8.5.0 | BSD-3-Clause | runtime |
| colorama | 0.4.6 | BSD (classifier) | dev |
| fastapi | 0.143.3 | MIT | runtime |
| h11 | 0.16.0 | MIT | runtime |
| httpcore | 1.0.9 | BSD-3-Clause | dev |
| httptools | 0.9.0 | MIT | runtime |
| httpx | 0.28.1 | BSD-3-Clause | dev |
| idna | 3.20 | BSD-3-Clause | runtime |
| iniconfig | 2.3.1 | MIT | dev |
| jsonschema | 4.26.0 | MIT | dev |
| jsonschema-specifications | 2025.9.1 | MIT | dev |
| opentelemetry-api | 1.45.1 | Apache-2.0 | runtime |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | dev |
| pluggy | 1.7.0 | MIT | dev |
| psycopg | 3.3.6 | LGPL-3.0-only | runtime |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | runtime |
| pydantic | 2.14.1 | MIT | runtime |
| pydantic-core | 2.50.1 | MIT | runtime |
| pygments | 2.21.0 | BSD-2-Clause | dev |
| pytest | 9.1.1 | MIT | dev |
| python-dotenv | 1.2.4 | BSD-3-Clause | runtime |
| pyyaml | 6.0.3 | MIT | runtime |
| referencing | 0.37.0 | MIT | dev |
| rpds-py | 2026.9.1 | MIT | dev |
| ruff | 0.17.1 | MIT | dev |
| sqlalchemy | 2.1.5 | MIT | runtime |
| starlette | 1.8.0 | BSD-3-Clause | runtime |
| typing-extensions | 4.16.0 | PSF-2.0 | runtime |
| typing-inspection | 0.4.4 | MIT | runtime |
| tzdata | 2026.5 | Apache-2.0 | runtime |
| uvicorn | 0.54.0 | BSD-3-Clause | runtime |
| uvloop | 0.23.0 | MIT OR Apache-2.0 (classifiers) | runtime |
| watchfiles | 1.3.0 | MIT | runtime |
| websockets | 17.2 | BSD-3-Clause | runtime |

## JavaScript: `frontend/package.json`

Added when the frontend lane (W4) merges and `frontend/package-lock.json` exists on `main`.

## RxNav drug class table (rule BL-AMOX-01)

{NLM statement line, added verbatim when the class table is committed}
