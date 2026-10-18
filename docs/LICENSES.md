# License inventory

Author: Christian Flores (docs) · 2026-10-18

This file lists the third-party packages in the repository's lock files, the container images and build tools installed outside them, and the data sources. The tables are maintained by hand: update them in the same pull request that changes a lock file, an image or a build step. Each license is the one the package declares in its own metadata. Nobody has checked these against the license files or reviewed them legally. Where a package declares only "BSD", the BSD variant is not stated.

The project's own code is released under the MIT License (`LICENSE` at the repository root). It covers the code only; the data sources below keep their own terms.

## Python: `uv.lock`

These are all 92 third-party packages in `uv.lock`; the project itself is the 93rd entry. Versions come from `uv.lock`. Licenses come from the installed package metadata (`importlib.metadata`), read from a `.venv` synced from this `uv.lock`, at the version pinned there. The "Read from" column shows where in that metadata the license came from: the `License-Expression` field (an SPDX expression), the free-text `License` field, or a `License ::` classifier. A package that is not installed on macOS is marked as such.

Scope: **runtime** packages are reached from `[project].dependencies` in `pyproject.toml`, including the `uvicorn[standard]` extra. **dev** packages are reached only from the `dev` and `train` dependency groups. That gives 42 runtime and 50 dev packages.

| Package | Version | License, as the package declares it | Read from | Scope |
|---|---|---|---|---|
| aiohappyeyeballs | 2.7.1 | PSF-2.0 | `License` field | dev |
| aiohttp | 3.14.5 | Apache-2.0 AND MIT | `License-Expression` | dev |
| aiosignal | 1.4.0 | Apache 2.0 | `License` field | dev |
| annotated-doc | 0.0.5 | MIT | `License-Expression` | runtime |
| annotated-types | 0.8.0 | MIT | `License-Expression` | runtime |
| anyio | 4.15.1 | MIT | `License-Expression` | runtime |
| attrs | 26.1.0 | MIT | `License-Expression` | dev |
| cbor2 | 6.1.5 | MIT | `License-Expression` | dev |
| certifi | 2026.7.22 | MPL-2.0 | `License` field | runtime |
| cffi | 2.1.1 | MIT-0 | `License-Expression` | runtime |
| charset-normalizer | 3.5.2 | MIT | `License` field | runtime |
| click | 8.5.0 | BSD-3-Clause | `License-Expression` | runtime |
| cloudpickle | 3.1.2 | BSD-3-Clause | `License` field | dev |
| colorama | 0.4.6 | unknown, check | not installed (Windows only: `sys_platform == 'win32'`) | dev |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | `License-Expression` | runtime |
| distro | 1.9.0 | Apache License, Version 2.0 | `License` field | runtime |
| fastapi | 0.143.3 | MIT | `License-Expression` | runtime |
| frozenlist | 1.8.0 | Apache-2.0 | `License` field | dev |
| google-auth | 2.62.0 | Apache 2.0 | `License` field | runtime |
| google-genai | 2.31.0 | Apache-2.0 | `License-Expression` | runtime |
| graphql-core | 3.2.13 | MIT license | `License` field | dev |
| grpclib | 0.4.9 | BSD-3-Clause | `License` field | dev |
| h11 | 0.16.0 | MIT | `License` field | runtime |
| h2 | 4.4.1 | MIT | `License-Expression` | dev |
| harfile | 0.5.0 | MIT | `License-Expression` | dev |
| hpack | 4.2.0 | MIT | `License-Expression` | dev |
| httpcore | 1.0.9 | BSD-3-Clause | `License-Expression` | runtime |
| httptools | 0.9.0 | MIT | `License-Expression` | runtime |
| httpx | 0.28.1 | BSD-3-Clause | `License` field | runtime |
| hyperframe | 6.1.0 | MIT License | classifier | dev |
| hypothesis | 6.170.1 | MPL-2.0 | `License-Expression` | dev |
| hypothesis-graphql | 0.13.2 | MIT | `License-Expression` | dev |
| idna | 3.20 | BSD-3-Clause | `License-Expression` | runtime |
| iniconfig | 2.3.1 | MIT | `License-Expression` | dev |
| jellyfish | 1.3.0 | MIT License | classifier | runtime |
| joblib | 1.6.0 | BSD-3-Clause | `License-Expression` | dev |
| jsonschema | 4.26.0 | MIT | `License-Expression` | dev |
| jsonschema-rs | 0.58.6 | MIT | `License` field | dev |
| jsonschema-specifications | 2025.9.1 | MIT | `License-Expression` | dev |
| markdown-it-py | 4.2.0 | MIT License | classifier | dev |
| markupsafe | 3.0.4 | BSD-3-Clause | `License-Expression` | dev |
| mdurl | 0.1.2 | MIT License | classifier | dev |
| metaphone | 0.6 | BSD | `License` field | runtime |
| modal | 1.6.2 | Apache-2.0 | `License-Expression` | dev |
| multidict | 7.1.0 | Apache-2.0 | `License-Expression` | dev |
| narwhals | 2.27.1 | MIT | `License-Expression` | dev |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | `License-Expression` | dev |
| opentelemetry-api | 1.45.1 | Apache-2.0 | `License-Expression` | runtime |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause | `License-Expression` | dev |
| pluggy | 1.7.0 | MIT | `License` field | dev |
| propcache | 0.5.4 | Apache-2.0 | `License` field | dev |
| protobuf | 7.36.2 | 3-Clause BSD License | `License` field | dev |
| psycopg | 3.3.6 | LGPL-3.0-only | `License-Expression` | runtime |
| psycopg-binary | 3.3.6 | LGPL-3.0-only | `License-Expression` | runtime |
| pyasn1 | 0.6.4 | BSD-2-Clause | `License` field | runtime |
| pyasn1-modules | 0.4.2 | BSD | `License` field | runtime |
| pycparser | 3.11 | BSD-3-Clause | `License-Expression` | runtime |
| pydantic | 2.14.1 | MIT | `License-Expression` | runtime |
| pydantic-core | 2.50.1 | MIT | `License-Expression` | runtime |
| pygments | 2.21.0 | BSD-2-Clause | `License-Expression` | dev |
| pyrate-limiter | 4.5.0 | MIT | `License-Expression` | dev |
| pytest | 9.1.1 | MIT | `License-Expression` | dev |
| python-dotenv | 1.2.4 | BSD-3-Clause | `License` field | runtime |
| pyyaml | 6.0.3 | MIT | `License` field | runtime |
| referencing | 0.37.0 | MIT | `License-Expression` | dev |
| requests | 2.34.2 | Apache-2.0 | `License` field | runtime |
| rich | 15.0.0 | MIT | `License` field | dev |
| rpds-py | 2026.9.1 | MIT | `License-Expression` | dev |
| ruff | 0.17.1 | MIT | `License-Expression` | dev |
| schemathesis | 4.31.1 | MIT | `License-Expression` | dev |
| scikit-learn | 1.9.1 | BSD-3-Clause | `License-Expression` | dev |
| scipy | 1.18.1 | BSD License | classifier | dev |
| sniffio | 1.3.1 | MIT OR Apache-2.0 | `License` field | runtime |
| sortedcontainers | 2.4.0 | Apache 2.0 | `License` field | dev |
| sqlalchemy | 2.1.5 | MIT | `License-Expression` | runtime |
| starlette | 1.8.0 | BSD-3-Clause | `License-Expression` | runtime |
| synchronicity | 0.12.6 | Apache Software License | classifier | dev |
| tenacity | 9.1.4 | Apache 2.0 | `License` field | runtime |
| threadpoolctl | 3.7.0 | BSD-3-Clause | `License-Expression` | dev |
| toml | 0.10.2 | MIT | `License` field | dev |
| types-certifi | 2021.10.8.3 | Apache-2.0 license | `License` field | dev |
| types-toml | 0.10.8.20260518 | Apache-2.0 | `License-Expression` | dev |
| typing-extensions | 4.16.0 | PSF-2.0 | `License-Expression` | runtime |
| typing-inspection | 0.4.4 | MIT | `License-Expression` | runtime |
| tzdata | 2026.5 | Apache-2.0 | `License` field in the uv cache's wheel metadata (Windows only: `sys_platform == 'win32'`, not installed on macOS) | runtime |
| urllib3 | 2.8.0 | MIT | `License-Expression` | runtime |
| uvicorn | 0.54.0 | BSD-3-Clause | `License-Expression` | runtime |
| uvloop | 0.23.0 | MIT License | `License` field | runtime |
| watchfiles | 1.3.0 | MIT | `License` field | runtime |
| websockets | 16.1.1 | BSD-3-Clause | `License-Expression` | runtime |
| werkzeug | 3.1.9 | BSD-3-Clause | `License-Expression` | dev |
| yarl | 1.25.1 | Apache-2.0 | `License` field | dev |

## JavaScript: `frontend/package.json` and `eval/acceptance/package.json`

These are the direct dependencies and devDependencies only; transitive packages are not listed. Versions come from each app's `package-lock.json`. Licenses come from `node_modules/<package>/package.json`, installed from those lock files, and every installed version equals its lock version.

### `frontend/` (13 dependencies, 14 devDependencies)

| Package | Version | License | Scope |
|---|---|---|---|
| @fontsource-variable/bricolage-grotesque | 5.3.0 | OFL-1.1 | runtime |
| @fontsource-variable/instrument-sans | 5.3.0 | OFL-1.1 | runtime |
| @fontsource/dm-mono | 5.3.0 | OFL-1.1 | runtime |
| @tanstack/react-query | 5.104.4 | MIT | runtime |
| cmdk | 1.1.1 | MIT | runtime |
| lucide-react | 1.59.0 | ISC | runtime |
| motion | 14.3.0 | MIT | runtime |
| next | 15.5.28 | MIT | runtime |
| openapi-fetch | 0.17.0 | MIT | runtime |
| react | 19.1.10 | MIT | runtime |
| react-dom | 19.1.10 | MIT | runtime |
| sonner | 2.0.8 | MIT | runtime |
| vitallens | 0.4.5 | MIT | runtime |
| @eslint/eslintrc | 3.3.7 | MIT | dev |
| @playwright/test | 1.64.1 | Apache-2.0 | dev |
| @tailwindcss/postcss | 4.3.3 | MIT | dev |
| @types/node | 22.20.5 | MIT | dev |
| @types/react | 19.3.0 | MIT | dev |
| @types/react-dom | 19.3.0 | MIT | dev |
| eslint | 9.39.5 | MIT | dev |
| eslint-config-next | 15.5.28 | MIT | dev |
| jsdom | 30.1.1 | MIT | dev |
| openapi-typescript | 7.13.0 | MIT | dev |
| prettier | 3.9.10 | MIT | dev |
| tailwindcss | 4.3.3 | MIT | dev |
| typescript | 5.9.3 | Apache-2.0 | dev |
| vitest | 5.0.5 | MIT | dev |

### `eval/acceptance/` (3 devDependencies)

| Package | Version | License | Scope |
|---|---|---|---|
| @playwright/test | 1.64.1 | Apache-2.0 | dev |
| @types/node | 26.6.5 | MIT | dev |
| typescript | 5.9.3 | Apache-2.0 | dev |


## Container images and build tools

| Component | Where | Version | License |
|---|---|---|---|
| `timescale/timescaledb-ha:pg18` | `docker-compose.yml` | pinned by digest (PG 18.6, TimescaleDB 2.30.2) | PostgreSQL License for PostgreSQL. TimescaleDB is Apache-2.0 for its core and Timescale License (TSL) for its community features, which include the continuous aggregates this repository uses. Other bundled extensions carry their own licenses. |
| `python:3.12-slim` | `backend/Dockerfile` | tag, not pinned by digest | Python under PSF-2.0 on a Debian base; Debian packages carry their own licenses |
| uv | `backend/Dockerfile` (`pip install uv`) | not pinned | MIT OR Apache-2.0 |
| Modal `debian_slim` image, Python 3.12 | `eval/sweep/modal_app.py` (the optional Modal sweep executor) | not pinned by digest | Python under PSF-2.0 on a Debian base; Debian packages carry their own licenses |
| uv binary from `ghcr.io/astral-sh/uv:latest` | `eval/sweep/modal_app.py` | `latest`, not pinned | MIT OR Apache-2.0 |

## Data sources

| Source | Where | License or terms |
|---|---|---|
| Synthea synthetic patients, November 2021 sample | `data/download.py` fetches it into the gitignored `data/raw`; never committed | Apache-2.0 |
| RxNav RxClass penicillin-class members and RxNorm ingredient lookups (NLM) | `backend/rule/cache/penicillin_class.json`, `backend/rule/cache/scd_to_ingredient.json`, offline snapshot fetched 2026-10-17 | **Placeholder for the lead:** the NLM statement still has to be added, verbatim from NLM's own terms. The docs lane has not written it. |
| DailyMed drug label excerpts (NLM) | `backend/rule/cache/labels/` | **Placeholder for the lead:** terms not recorded yet. |
| b.well public synthetic patient-matching benchmark, derived from ONC challenge data | Evaluation only; never committed (`.gitignore`: `data/onc/`, `data/benchmark/`) | Described by the test-set authors as synthetic; terms not located |

## RxNav drug class table (rule BL-AMOX-01)

{NLM statement line, added verbatim when the class table is committed}

<!-- lead: the class table is now committed (backend/rule/cache/penicillin_class.json); the NLM statement above is still a placeholder and needs the verbatim text. -->
