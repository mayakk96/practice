# Final verification record

Verified on 2026-11-11. This record reports completed checks for the new Python/JavaScript project. Existing tracked Java project files remain unchanged. No commit, branch, pull request, source upload or deployment was sent to GitHub.

## Automated checks actually completed

| Check | Result |
| --- | --- |
| Full pytest suite with PostgreSQL17 and Kafka3.9.1 available | **118 passed; zero skipped** |
| Statement coverage of `app` during that run | **86%** |
| Separate mock-network unittest suite | **5 passed** |
| JavaScript exact-money, authentication and error regression tests | **4 passed** |
| Vite production build | Passed |
| Ruff lint and format checks for backend/scripts/mock | Passed |
| Python compilation | Passed |
| Alembic migration/application metadata alignment | Passed for SQLite and PostgreSQL |
| Standard Compose configuration | Passed |
| Independent GitHub Actions workflow YAML parsing | Passed; workflow has not run on GitHub |
| All six local Compose services | Healthy |
| Secured nginx/React production browser workflow | Passed desktop and mobile; zero JavaScript runtime errors |
| Packaged runbook check | Wheel included all eight synthetic runbooks |
| Source hygiene | No generated local credentials or build output in review source; original tracked files unchanged |

The full Python command was run from `backend/`, with `TEST_DATABASE_URL` set to an isolated PostgreSQL17 database and `KAFKA_BOOTSTRAP_SERVERS` / `TEST_KAFKA_BOOTSTRAP_SERVERS` set to the real broker:

```sh
pytest -q --cov=app --cov-report=term --cov-report=xml:coverage.xml --junitxml=pytest.xml
```

PostgreSQL tests create and remove isolated schemas. Kafka tests create isolated topics. This run included uniqueness/idempotency races, concurrent capture and settlement, exception compare-and-set, consumer/projection races, publishing/duplicates/DLT, and migration alignment. SQLite alone is not offered as proof of PostgreSQL locks. One upstream Starlette warning recommends its newer test transport; it did not cause a test failure.

Other executed checks:

```sh
python3 -m unittest discover -s demo/network-service -p 'test_*.py'
ruff check backend scripts demo
ruff format --check backend scripts demo
python3 -m py_compile scripts/*.py
docker compose config --quiet
cd frontend
npm test
npm run build
BROWSER_BASE_URL=http://127.0.0.1:5173 npm run test:browser
```

The cloud browser check selected the installed system Chromium explicitly, disabled its sandbox only for this managed container, and read generated demo credentials from ignored `.env` without printing them. A normal local run can install Playwright Chromium as described in `TESTING.md`.

## Live financial demonstrations

These ran successfully against the secured Compose API backed by PostgreSQL, the HTTP mock network and the Kafka worker:

```sh
python3 scripts/demo_end_to_end.py --run-id review-final
python3 scripts/demo_duplicate_transaction.py
python3 scripts/load_test.py --count 100 --concurrency 4
python3 scripts/demo_network_timeout.py
```

The full demonstration exercised original-response idempotent replay and conflicting-body409, authorization/capture/clearing, settlement confirmation, internal50000 versus external45000 with5000 variance, a linked exception and read-only assistant, decline, captured reversal, and full refund with opposite settlement direction. Eight concurrent duplicate submissions returned one201 and seven200 replays for one UUID.

The timeout script ran while the local mock was deliberately configured for persistent timeout, then the mock was restored to normal. It returned503 and left the instruction RECEIVED because the local authorization transaction rolled back. Remote acceptance remained ambiguous; stable references were retained.

The100-request acceptance-only workload recorded zero errors, approximately94.83 successful requests/second, p50 approximately38.54ms, p95 approximately77.16ms and p99 approximately89.79ms. These are observations from this cloud executor, not a production capacity or end-to-end settlement benchmark.1000/10000-request workloads are supported by the script but were not run as final benchmarks.

The real browser test logged in through nginx, kept credentials out of local/session storage, created a13456-minor-unit payment, authorized/captured/cleared/settled it, imported8456 external evidence, inspected the5000 mismatch, retrieved cited assistance, investigated/resolved the exception with audited versions, and confirmed financial state did not change during resolution. It also exercised all navigation sections and a390px mobile viewport with no overflow. Final screenshots show real synthetic PostgreSQL data and Kafka projections. Worker metrics reported zero pending outbox events and zero consumer lag after processing.

## Docker environment and cloud-specific limits

The backend and frontend production Dockerfiles were built successfully using a temporary BuildKit CA-secret override required by this managed proxy. The checked-in Dockerfiles keep TLS validation enabled and support that optional CA mount without storing its contents in an image.

This executor has a7.9GB writable filesystem and Docker's VFS storage driver, whose cumulative image snapshots exhausted disk. For the simultaneous full environment only, scratch overrides referenced locally flattened PostgreSQL/Kafka images. Their exported runtime configuration and filesystem content, mode, ownership and links were verified equal to the original official images, excluding Docker-injected hostname/hosts/resolv/.dockerenv files. Application source, PostgreSQL version and Kafka version were unchanged.

A final frontend rebuild after the browser authentication fix hit the same storage limit. The final production container therefore used the successfully built nginx runtime with the exact final locally built Vite assets copied in and the corrected local healthcheck. The secured browser suite passed against that container. The standard checked-in multi-stage Dockerfile contains the same source and builds those assets in ordinary environments; the final patched frontend Dockerfile was not rebuilt end-to-end here after the disk failure. Its source build and its final runtime were verified separately.

All six services—API, frontend, PostgreSQL, Kafka, mock network and worker—were healthy together. Nginx health uses `wget -Y off` so loopback probes bypass inherited proxy variables. No cloud-only image tag, credential, CA file or scratch override is committed in the source project.

## Scope and publication

This is a fictional educational system: no real rails, funding availability, complete general ledger, OIDC/TLS deployment, partial refunds, FX or regulatory certification is claimed. External reconciliation evidence is append-only; replacement/supersession is a documented future policy. AWS/multi-region documents are design exercises. Hosted CI and remote deployment remain unexecuted because the user requested review and permission before any upload or push.
