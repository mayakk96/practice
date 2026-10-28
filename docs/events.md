# Durable onboarding events

REST handles a request synchronously: the caller receives a result or a clear error before continuing. Kafka decouples work in time: onboarding commits an event, and another consumer processes it later. A successful REST request does **not** promise that the audit consumer has already finished. Status history is written synchronously in the business transaction; Kafka audit is a separate asynchronous example.

## Flow and transaction boundaries

1. An onboarding service changes business tables in a database transaction.
2. `DomainEventRecorder` inserts an `event_outbox` row inside that same transaction. Its `MANDATORY` propagation rejects accidental use outside a business transaction. If the business change rolls back, the outbox insert rolls back with it.
3. `OutboxDispatcher` polls when `application.events.enabled=true`. It processes at most `application.events.batch-size` rows per pass. `OutboxDeliveryService` locks and sends **one event per database transaction**, with a bounded broker-acknowledgement wait.
4. The dispatcher marks a row published only after Kafka acknowledges the send. Producer idempotence and `acks=all` are configured, but those features do not turn the combined database/Kafka operation into an exactly-once transaction.
5. `OnboardingAuditConsumer` deserializes and validates the envelope. `AuditEventService` commits a durable inbox/audit record before returning to the listener. The listener's `RECORD` acknowledgement mode then permits the offset to be committed.

The deliberate tradeoff is a short database row lock while awaiting Kafka. The default acknowledgement wait is two seconds and cannot exceed ten seconds; each delivery transaction has a fifteen-second timeout. A larger deployment would typically use a dedicated CDC/outbox relay, explicit claim leases, or additional partitioned dispatch workers. This portfolio keeps the atomicity and failure cases visible in ordinary Java code.

## Schema and data boundaries

The four event names are `OnboardingCaseCreated`, `DocumentSubmitted`, `OnboardingStatusChanged`, and `OnboardingCompleted`. All use schema version `1`:

```json
{
  "eventId": "f434af51-92db-4a19-9203-c8a8a54a182e",
  "eventType": "OnboardingStatusChanged",
  "caseId": "3c5bf0c7-5b14-4580-a119-d99bb25bd35c",
  "occurredAt": "2026-01-01T12:00:00Z",
  "schemaVersion": 1,
  "payload": {
    "previousStatus": "UNDER_REVIEW",
    "newStatus": "APPROVED",
    "riskLevel": "LOW"
  }
}
```

`EventMetadata` allowlists event names, identifier fields, and known enum values. Names, email addresses, document references, free-text reasons and arbitrary payload fields are rejected. The audit table keeps identifiers, event type, timestamps and a SHA-256 fingerprint, rather than copying the complete payload. Application event logs contain only these safe identifiers and fixed failure classifications.

The consumer rejects unknown schema versions. A real schema evolution would introduce backward-compatible optional fields, a new topic/version where necessary, and consumer deployment/migration rules. This example intentionally has one explicit, tested version rather than an unimplemented schema-registry claim.

## Topic, key and consumer group

The default topic is `onboarding.events.v1`, with three partitions and one replica for local demonstration. The Kafka record key is `caseId`, so events for one case share a partition. `onboarding-audit-v1` is the default consumer group: group members share partitions; a different group can independently process every event for a different purpose.

Outbox rows have a database-generated sequence. The dispatcher does not select a later unpublished event for the same case while an earlier one remains pending. This preserves per-case publication order, including when an earlier row is backing off after a broker failure. It does not impose ordering across unrelated cases. The case service's database locking serializes mutations to an individual case.

The default topic has a single replica because Compose runs one local broker. A production deployment would require replicated topics, suitable minimum in-sync replica settings, capacity planning, access controls, encryption and a managed retention policy.

## Failures, retries and duplicate events

Database and Kafka cannot commit atomically in this design. If Kafka accepted a record but the application crashed before recording `published_at`, the dispatcher sends it again. An acknowledgement timeout can likewise lead to a resend even if the original send eventually succeeded. The delivery guarantee is **at least once**.

Outbox failures retain the row, increment `attempts`, store a safe fixed classification, and retry with exponential backoff capped at sixty seconds. The same-case ordering rule blocks later events for that case until the older row succeeds; unrelated cases continue. Persisted pending rows survive application restarts. Rows are retained after success so the behavior is inspectable; a production system needs monitored cleanup/retention, escalation for persistent failures, and an operational replay procedure.

The audit consumer deduplicates by the primary key `event_id`. A normal replay returns without adding a row. `AuditEvent` implements Spring Data `Persistable`: a newly constructed audit record is always inserted even though its UUID is already assigned. Otherwise, JPA's default `save` behavior could merge over a winning insert that committed between an existence check and the subsequent save. If two consumers race, the losing insert rolls back before the code reads the winner in a new transaction. Catching a unique-key failure and continuing inside the already-aborted transaction would be incorrect on PostgreSQL. A reused event ID with different content is rejected rather than silently accepted. `AuditInsertRaceIntegrationTest` forces that exact interleaving and checks both matching and conflicting replays without relying on thread timing.

Transient consumer failures are retried twice with a fixed short backoff. Exhausted failures are sent to `<topic>.DLT`; malformed/unsupported envelopes go there immediately. A failed dead-letter send is itself treated as a failure, so the source record is not silently acknowledged. The dead-letter topic has matching partitions. An operator would investigate the cause and replay deliberately after correction; the project does not automatically replay or discard DLT records.

Do not log raw Kafka records or exception text from untrusted payloads. Kafka infrastructure libraries can include record information in diagnostic errors; access to broker logs and dead-letter topics must be restricted in a real deployment, and this demo must use fictional data only.

## Configuration and monitoring

Kafka processing is disabled in the isolated demo/test defaults; business changes still create outbox rows. Enable processing with `APPLICATION_EVENTS_ENABLED=true` and configure `KAFKA_BOOTSTRAP_SERVERS` (Compose does this). Key settings are:

| Setting | Default | Purpose |
| --- | --- | --- |
| `application.events.topic` | `onboarding.events.v1` | Main event topic |
| `application.events.consumer-group` | `onboarding-audit-v1` | Independent audit subscription |
| `application.events.batch-size` | `10` | Maximum deliveries per poll |
| `application.events.poll-interval` | `2000` | Poll delay in milliseconds |
| `application.events.publish-timeout` | `2s` | Maximum broker-acknowledgement wait |
| `application.events.retry-backoff` | `1s` | Initial outbox/consumer retry delay |

Micrometer counters include `onboarding.events.published`, `onboarding.events.publish.failures`, `onboarding.events.consumed` and `onboarding.events.duplicates`. They are process-local operational counters; they are not financial records and are not an exactly-once ledger. A database rollback, restart or crash can make them differ from durable row totals. Monitor pending outbox count/oldest age, repeated failures, DLT growth, consumer lag, broker/database availability and processing latency as separate signals.

## Automated evidence

`EventMetadataTest` checks supported schemas and the payload allowlist. `OutboxDeliveryServiceTest` checks acknowledgement-before-marking, case keys, broker failures and bounded timeout behavior. `EventPersistenceIntegrationTest` uses Flyway/H2 to check transactional rollback, ordered selection and concurrent inbox deduplication. `KafkaEventIntegrationTest` starts an actual in-process Kafka broker and exercises outbox-to-producer-to-consumer delivery, duplicate transport replay, and the dead-letter path. It requires local socket support but no Docker daemon or external broker.

The PostgreSQL/Testcontainers profile separately validates the real database migrations and application behavior. Testcontainers outcomes and any Docker/runtime limitations are reported separately from the default test suite.
