# Observability and operational thinking

## Implemented signals

The application uses Actuator/Micrometer and structured ECS JSON console logging. Safe health/info endpoints are public; metrics endpoints require the operator when development security is enabled.

| Endpoint | Purpose |
| --- | --- |
| `/actuator/health` | Aggregate health without component details |
| `/actuator/health/liveness` | Process/application liveness state |
| `/actuator/health/readiness` | Readiness state plus database availability |
| `/actuator/info` | Non-sensitive application description |
| `/actuator/metrics` | Named Micrometer meters |
| `/actuator/prometheus` | Scrape format for an external Prometheus installation |

Prometheus/Grafana and an alerting system are not bundled. Readiness deliberately includes the database; async broker delivery has a different availability/lag concern. A live JVM can still be unready to serve a database-dependent request.

## Correlation and privacy

A request correlation ID is accepted only in a bounded safe form or replaced with a generated ID. It appears in the response and logging context, allowing a caller-visible failure to be traced through technical logs. The filter clears logging context after the request so reused servlet threads do not inherit another request's ID.

Workflow logs identify case/event IDs and states. They do not log applicant names/email, document references, free-text reasons, policy queries, credentials, Authorization headers or downstream response bodies. UUIDs are still operational identifiers, so production log access and retention should remain controlled.

Correlation IDs support troubleshooting. They are not authentication tokens and should not be used as authorization decisions. Full distributed tracing additionally needs trace/span propagation and an exporter.

## Read the meters as questions

HTTP server meters expose request count, duration and response classifications. JVM/pool meters describe runtime resources. Business gauges include `onboarding.cases` with seven bounded status labels and `onboarding.events.pending`. Event counters include `onboarding.events.published`, `onboarding.events.publish.failures`, `onboarding.events.consumed`, and `onboarding.events.duplicates`. Screening retry decisions are logged; the wrapper does not claim a separate custom retry counter. Discover registered names through `/actuator/metrics` rather than assuming an external dashboard already exists. The database-backed gauges issue count queries at scrape time; a large deployment would evaluate their cost and use an appropriate aggregate/read model.

| What to watch | Why it matters | Example response |
| --- | --- | --- |
| Request volume / latency / error rate | Detect load, regressions and failed workflows | Compare p95/p99, status and route trends |
| Screening attempts/failures and elapsed time | Separate vendor trouble from local validation | Inspect bounded retries; avoid retry amplification |
| Database health / pool saturation | A running server may be unable to transact | Check readiness, connection waits, slow queries |
| Pending outbox rows / publish failures | Business commits can succeed while delivery is delayed | Alert on age as well as count |
| Audit consumed/duplicate events | Understand at-least-once replay and consumer health | Compare published and consumed progress |
| Kafka consumer lag / DLT records | Identify stuck consumers or poison events | Inspect lag externally and triage DLT safely |
| Completed / rejected cases | Track domain outcomes | Use event/business counters, not raw error logs |
| JVM memory, GC and thread counts | Detect resource pressure | Tune from measurements and load tests |

Consumer lag, dead-letter queues, business completion rates and production SLOs need a real monitoring system and operational thresholds. The repository demonstrates the signals and architecture; it does not ship a production control plane.

## Failure scenarios worth rehearsing

1. Stop the mock provider: approval should fail predictably without committing a partial transition.
2. Stop Kafka: HTTP business transactions can still create durable outbox rows; inspect pending work and recovery after restart.
3. Replay an event: verify one audit effect and a duplicate signal.
4. Stop PostgreSQL: readiness should fail and database-dependent API calls should not claim success.
5. Supply an invalid request ID: the filter should produce a safe replacement rather than copying arbitrary text into logs.

Only stop services you started for the local exercise. Production drills need approved runbooks, impact boundaries and rollback criteria.
