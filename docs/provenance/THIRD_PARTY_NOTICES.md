# Riverline third-party provenance report

Generated deterministically by `py -3.13 tools/generate_license_provenance.py`; it has no timestamp and does not contact a network service.

Riverline is licensed under **AGPL-3.0-or-later**. Network users must be offered Corresponding Source as required by AGPL section 13. Non-commercial use is not a license exemption. This report is engineering evidence, not legal advice.

## Source repository release: PASS

## Bundled binary/container release: FAIL

This stricter verdict applies only when publishing a Docker image, wheel, installer, or another artifact that contains runtime binaries. A source-only GitHub branch/PR merge does not convey `node_modules`, Python wheels, or libvips binaries.

The bundled-artifact gate is fail-closed for:

- `npm:@img/colour: binary/container artifact integrity hash is not locked`
- `npm:@img/sharp-libvips-darwin-arm64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-darwin-x64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-arm64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-arm: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-ppc64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-riscv64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-s390x: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linux-x64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linuxmusl-arm64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-libvips-linuxmusl-x64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-wasm32: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-win32-arm64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-win32-ia32: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@img/sharp-win32-x64: binary/container artifact integrity hash is not locked`
- `npm:@img/sharp-win32-x64: bundled binary/container release requires verification of the actual shipped binary, notices, and corresponding-source handling`
- `npm:@next/env: binary/container artifact integrity hash is not locked`
- `npm:@next/swc-win32-x64-msvc: binary/container artifact integrity hash is not locked`
- `npm:@swc/helpers: binary/container artifact integrity hash is not locked`
- `npm:@types/node: binary/container artifact integrity hash is not locked`
- `npm:@types/react-dom: binary/container artifact integrity hash is not locked`
- `npm:@types/react: binary/container artifact integrity hash is not locked`
- `npm:baseline-browser-mapping: binary/container artifact integrity hash is not locked`
- `npm:caniuse-lite: binary/container artifact integrity hash is not locked`
- `npm:client-only: binary/container artifact integrity hash is not locked`
- `npm:csstype: binary/container artifact integrity hash is not locked`
- `npm:detect-libc: binary/container artifact integrity hash is not locked`
- `npm:nanoid: binary/container artifact integrity hash is not locked`
- `npm:picocolors: binary/container artifact integrity hash is not locked`
- `npm:postcss: binary/container artifact integrity hash is not locked`
- `npm:react-dom: binary/container artifact integrity hash is not locked`
- `npm:react: binary/container artifact integrity hash is not locked`
- `npm:scheduler: binary/container artifact integrity hash is not locked`
- `npm:semver: binary/container artifact integrity hash is not locked`
- `npm:sharp: binary/container artifact integrity hash is not locked`
- `npm:source-map-js: binary/container artifact integrity hash is not locked`
- `npm:styled-jsx: binary/container artifact integrity hash is not locked`
- `npm:tslib: binary/container artifact integrity hash is not locked`
- `npm:typescript: binary/container artifact integrity hash is not locked`
- `npm:undici-types: binary/container artifact integrity hash is not locked`
- `pypi:alembic: binary/container artifact integrity hash is not locked`
- `pypi:annotated-doc: binary/container artifact integrity hash is not locked`
- `pypi:annotated-types: binary/container artifact integrity hash is not locked`
- `pypi:anyio: binary/container artifact integrity hash is not locked`
- `pypi:certifi: binary/container artifact integrity hash is not locked`
- `pypi:click: binary/container artifact integrity hash is not locked`
- `pypi:colorama: binary/container artifact integrity hash is not locked`
- `pypi:fakeredis: binary/container artifact integrity hash is not locked`
- `pypi:fastapi: binary/container artifact integrity hash is not locked`
- `pypi:greenlet: binary/container artifact integrity hash is not locked`
- `pypi:h11: binary/container artifact integrity hash is not locked`
- `pypi:httpcore: binary/container artifact integrity hash is not locked`
- `pypi:httpx: binary/container artifact integrity hash is not locked`
- `pypi:idna: binary/container artifact integrity hash is not locked`
- `pypi:iniconfig: binary/container artifact integrity hash is not locked`
- `pypi:mako: binary/container artifact integrity hash is not locked`
- `pypi:markupsafe: binary/container artifact integrity hash is not locked`
- `pypi:packaging: binary/container artifact integrity hash is not locked`
- `pypi:pluggy: binary/container artifact integrity hash is not locked`
- `pypi:pokerkit: binary/container artifact integrity hash is not locked`
- `pypi:psycopg-binary: binary/container artifact integrity hash is not locked`
- `pypi:psycopg-pool: binary/container artifact integrity hash is not locked`
- `pypi:psycopg: binary/container artifact integrity hash is not locked`
- `pypi:pydantic-core: binary/container artifact integrity hash is not locked`
- `pypi:pydantic: binary/container artifact integrity hash is not locked`
- `pypi:pygments: binary/container artifact integrity hash is not locked`
- `pypi:pytest: binary/container artifact integrity hash is not locked`
- `pypi:python-dotenv: binary/container artifact integrity hash is not locked`
- `pypi:redis: binary/container artifact integrity hash is not locked`
- `pypi:sortedcontainers: binary/container artifact integrity hash is not locked`
- `pypi:sqlalchemy: binary/container artifact integrity hash is not locked`
- `pypi:starlette: binary/container artifact integrity hash is not locked`
- `pypi:typing-extensions: binary/container artifact integrity hash is not locked`
- `pypi:typing-inspection: binary/container artifact integrity hash is not locked`
- `pypi:uvicorn: binary/container artifact integrity hash is not locked`

## Reviewed copyleft decisions

- `@img/sharp-win32-x64` is locked as `Apache-2.0 AND LGPL-3.0-or-later`. It carries a Windows libvips binary through the sharp package family. The explicit decision allows review of this known package only; a distributor must retain applicable notices and provide or point to the corresponding LGPL source/license materials for the shipped binary. Evidence: <https://github.com/lovell/sharp-libvips/blob/main/LICENSE> and <https://github.com/lovell/sharp-libvips>. This is not a legal conclusion.
- Optional Python `psycopg`, `psycopg-binary`, and `psycopg-pool` are explicitly recorded LGPL-3.0-only dependencies. Their notice/source obligations remain applicable if they are distributed.
- No new GPL/AGPL runtime dependency is permitted by this gate; Riverline's own AGPL-3.0-or-later license is recorded separately.

## Machine-readable inventory

See [`sbom.json`](sbom.json). Every record includes ecosystem, name, version, direct/transitive classification, source, resolved location, integrity, license, evidence, and unknown fields.
