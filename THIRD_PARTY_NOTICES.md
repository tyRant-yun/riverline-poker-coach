# Riverline third-party notices and provenance ledger

Updated: 2026-08-12

Riverline is licensed under `AGPL-3.0-or-later`; see [`LICENSE`](LICENSE). Third-party components remain under their own licenses. This ledger is an engineering provenance record, not legal advice and not a substitute for the license files shipped in each distribution.

## Current direct components

Versions below are the repository-pinned versions in `backend/pyproject.toml`, `backend/requirements.lock`, `frontend/package.json`, and `frontend/package-lock.json`. “Direct” means selected by Riverline rather than merely resolved transitively.

| Component | Version / source | Riverline use | Declared license | Relationship | Decision | Required provenance |
|---|---|---|---|---|---|---|
| [PokerKit](https://github.com/uoftcprg/pokerkit) | `0.7.4`, PyPI/upstream tag | Only online poker rules authority and current showdown baseline | MIT | Direct runtime | Adopted; all access stays behind `rules/pokerkit_adapter.py` | Exact wheel hash, upstream tag, bundled license, adapter regression results |
| [Pydantic](https://github.com/pydantic/pydantic) | `2.13.4` | Domain and wire-contract validation | MIT | Direct runtime | Adopted | Wheel/hash, license, schema compatibility test result |
| [FastAPI](https://github.com/fastapi/fastapi) | `0.139.2` | HTTP API boundary | MIT | Direct runtime | Adopted | Wheel/hash, license |
| [Uvicorn](https://github.com/encode/uvicorn) | `0.51.0` | ASGI process | BSD-3-Clause | Direct runtime | Adopted | Wheel/hash, license |
| [SQLAlchemy](https://github.com/sqlalchemy/sqlalchemy) | `2.0.51` | Database abstraction | MIT | Direct runtime | Adopted | Wheel/hash, license |
| [Alembic](https://github.com/sqlalchemy/alembic) | `1.19.1` | Database migrations | MIT | Direct runtime | Adopted | Wheel/hash, license, migration provenance |
| [HTTPX](https://github.com/encode/httpx) | `0.28.1` | HTTP client/test transport | BSD-3-Clause | Direct runtime/test | Adopted | Wheel/hash, license |
| [python-dotenv](https://github.com/theskumar/python-dotenv) | `1.2.2` | Local configuration loading | BSD-3-Clause | Direct runtime | Adopted | Wheel/hash, license |
| [psycopg](https://github.com/psycopg/psycopg) / psycopg-binary | `3.3.4` | Optional PostgreSQL driver | LGPL-3.0-only | Direct optional runtime | Adopted optional | Wheel/hash per platform, LGPL text, source offer/location for distributed binary |
| [psycopg-pool](https://github.com/psycopg/psycopg) | `3.3.1` | Optional PostgreSQL pooling | LGPL-3.0-only | Direct optional runtime | Adopted optional | Wheel/hash, LGPL text |
| [redis-py](https://github.com/redis/redis-py) | `8.1.0` | Optional queue/cache client | MIT | Direct optional runtime | Adopted optional | Wheel/hash, license |
| [pytest](https://github.com/pytest-dev/pytest) | `9.1.1` | Python tests | MIT | Direct development | Adopted | Wheel/hash, license |
| [fakeredis](https://github.com/cunla/fakeredis-py) | `2.37.0` | Offline Redis test double | MIT | Direct development | Adopted | Wheel/hash, license |
| [Next.js](https://github.com/vercel/next.js) | `16.1.0` | Web application framework | MIT | Direct runtime | Adopted | npm integrity, license |
| [React](https://github.com/facebook/react) / React DOM | `19.2.0` | UI runtime | MIT | Direct runtime | Adopted | npm integrity, license |
| [TypeScript](https://github.com/microsoft/TypeScript) | `5.9.3` | Static type checking | Apache-2.0 | Direct development | Adopted | npm integrity, license/NOTICE |
| [Vite](https://github.com/vitejs/vite) | `^6.4.3` | Frontend test/build tooling | MIT | Direct development | Adopted | Resolved version and npm integrity, license |
| [Vitest](https://github.com/vitest-dev/vitest) | `^3.2.7` | Frontend unit tests | MIT | Direct development | Adopted | Resolved version and npm integrity, license |
| [Playwright](https://github.com/microsoft/playwright) | `1.62.1` | Browser E2E | Apache-2.0 | Direct development | Adopted | npm integrity, browser binary version, license/NOTICE |
| Testing Library packages | versions in `frontend/package-lock.json` | Component tests | MIT | Direct development | Adopted | Resolved versions, npm integrity, licenses |

The deterministic offline source-repository inventory is checked in at [`docs/provenance/sbom.json`](docs/provenance/sbom.json), with a human-readable companion at [`docs/provenance/THIRD_PARTY_NOTICES.md`](docs/provenance/THIRD_PARTY_NOTICES.md). Run `py -3.13 tools/generate_license_provenance.py --check` to fail closed for an unknown license/source, a prohibited GPL/AGPL runtime dependency, or a copyleft package without an explicit decision record.

The inventory distinguishes a source-only GitHub branch/PR merge from a bundled binary/container release. The former conveys neither `node_modules`, Python wheels, nor libvips binaries and currently passes its provenance gate. The latter remains blocked until artifact hashes and distribution-specific NOTICE/source obligations are verified. In particular, `@img/sharp-win32-x64` / libvips is recorded as `Apache-2.0 AND LGPL-3.0-or-later`; retain the applicable notice and provide or point to its corresponding LGPL source/license material whenever that binary is actually distributed. This is an engineering record, not legal advice, and non-commercial use is not an exemption.

## Standards, candidates, and research-only components

“Not installed” means the component is not part of the main runtime dependency graph at F0.

| Component | Version / source reviewed | Intended use | Declared license | Direct dependency? | F0 decision | Provenance/adoption requirement |
|---|---|---|---|---|---|---|
| [PHH](https://github.com/uoftcprg/phh-std) | Upstream specification/repository reviewed 2026-08-12 | Completed-hand import/export and fixtures | MIT | No | Adopt in F1 as an exchange format, never as the internal event log | Pin spec revision and parser version; preserve source hand ID and import warnings |
| [PH Evaluator / `phevaluator`](https://github.com/HenryRLee/PokerHandEvaluator) | Candidate repository reviewed; package absent locally | Optional 5–7 card evaluator acceleration | Apache-2.0 | No | Conditional; F0 adoption gate failed because differential, wheel/packaging, and local distribution-license checks could not run | Exact wheel/hash/version, bundled LICENSE/NOTICE, 0 differential mismatches, supported Python 3.13/Windows/Linux packaging, representative ≥2× p50 speedup |
| [PettingZoo](https://github.com/Farama-Foundation/PettingZoo) | Interface semantics reviewed | Agent-environment contract and future offline adapter | MIT | No | Learn contract only; not the online rules engine | Pin revision for any copied idea; independently implement adapter over Riverline observations |
| [OpenSpiel](https://github.com/google-deepmind/open_spiel) | Research framework reviewed | CFR correctness and small-game experiments | Apache-2.0 | No | Research-only package, isolated from online runtime | Separate research lockfile/environment, commit/tag and artifact provenance |
| [RLCard](https://github.com/datamllab/rlcard) | Research framework reviewed | Offline trajectories and agent experiments | MIT | No | Research only; never a rules or strategy truth source | Separate environment and explicit action-abstraction metadata |
| [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) | Candidate reviewed | F6 spaced-review scheduling behind a port | MIT | No | Deferred to learning phase | Pin version, license, UTC/timezone contract and scheduler-parameter provenance |
| [eventsourcing](https://github.com/pyeventsourcing/eventsourcing) | Candidate/pattern source reviewed | Event-store pattern comparison | BSD-3-Clause | No | Do not add in F0/F1; use a thin Riverline event layer first | A future adoption requires a migration spike and dependency/license record |
| [postflop-solver](https://github.com/b-inary/postflop-solver) | External research sidecar previously tested; not vendored | Offline HU postflop artifact production | AGPL-3.0-or-later | No main dependency | Do not embed or add to the main dependency graph; optional research producer only | Exact commit, source availability, build recipe, modifications, engine license and every artifact's config/version/accuracy provenance |
| [TexasSolver](https://github.com/bupticybee/TexasSolver) | Candidate reviewed | Cross-validation only | AGPL-3.0 | No | Not adopted | Same AGPL/source/artifact controls; explicit product-owner review before any use |
| [TexasHoldemSolverJava](https://github.com/bupticybee/TexasHoldemSolverJava) | Historical candidate reviewed | Possible solver adapter comparison | MIT | No | Deferred/not selected | Revalidate maintenance, exact commit, license and output correctness before a spike |
| [PyPokerEngine](https://github.com/ishikota/PyPokerEngine) | Historical interface reviewed | Callback/emulator ideas | MIT | No | Design reference only | No copied engine code; cite revision if design is reused |
| [MIT Pokerbots engine](https://github.com/mitpokerbots/engine) | Repository reviewed with no root license grant | Subprocess-isolation ideas | No license grant found | No | Code and assets must not be copied | Record repository/revision as an idea source only; independently implement protocols |
| Treys / Deuces / OMPEval | Repositories listed in `docs/research-poker-simulator-reuse.md` | Historical evaluator comparison | MIT / MIT / ISC | No | Not adopted | Re-open license/version review only if the evaluator decision is revisited |
| PokerRL / `poker_ai` / openCFR | Repositories listed in reuse research | Algorithm research | MIT / GPL / MIT | No | Not adopted | Isolated research only; never label outputs as production strategy without artifact provenance |

## Provenance policy

Every new or upgraded dependency, data file, model, strategy table, solver result, or generated artifact must record:

1. canonical upstream URL and exact release/tag/commit;
2. package integrity hash or source commit, plus the license and NOTICE files from that exact distribution;
3. whether it is runtime, optional, development, research-only, or an external artifact producer;
4. local modifications and build flags/patches;
5. for strategy/evaluator/solver artifacts: input ranges, rules, stacks, rake/ante, action tree, seed, algorithm, accuracy/convergence, producer version, and artifact fingerprint;
6. the approving ADR or task and the validation evidence used at adoption time.

Public availability, a project name containing “MIT,” or non-commercial use is not a license grant. Process/container/HTTP isolation is useful architecture but is not treated as an automatic license safe harbor. Release owners must satisfy Riverline's AGPL obligations and every compatible third-party obligation.
