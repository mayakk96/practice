# Hypothetical multi-region design exercise

**Design only.** This repository runs a local single-database application. It does not provision, deploy or prove a multi-region bank platform. The following decisions are proposals to reason about, not implemented guarantees.

## Prefer a controlled writer before active/active money commands

An active/passive regional arrangement is easier to reason about for unique transaction instructions, refund allocations and settlement membership. Route financial writes to one authoritative writer. A standby region can run read replicas and prepared application capacity, but promotion must fence the old writer before accepting commands. DNS change alone does not prevent split brain.

Active/active may be appropriate for read traffic or independently partitioned ownership. Global money writes need a defined home-region/partitioning scheme or a datastore with suitable global consistency and latency tradeoffs. Conflict resolution cannot simply use “last write wins” for a full refund or journal. Unique keys local to two isolated databases do not provide global uniqueness.

## State replication and failure objectives

Define RPO as acceptable committed-data loss and RTO as acceptable recovery time for each business function. Example proposed targets might be near-zero RPO for authoritative journal writes and an RTO of 15 minutes, but they are aspirations until tested. Asynchronous replication can lose acknowledged writes on sudden failover; synchronous cross-region replication adds latency and may reduce availability under partition.

Database replication, backups and point-in-time recovery serve different failure modes. A replicated accidental delete is still a delete; immutable backups and restoration drills remain necessary. Retain outbox events and consumer receipts consistently with the authoritative database state during promotion.

Kafka cross-region replication must address topic naming, partition keys, offsets, event identities, duplicate delivery and consumer failover. A replicated topic is not automatically a globally ordered log. Projection consumers remain idempotent and version-aware; recovery must verify broker retention covers the required replay.

## Routing, residency and controls

Regional routing should distinguish read access, command ownership and incident mode. Data residency may restrict customer/account replication or require regional encryption keys and approved operational access. Synthetic local demo data does not remove these design obligations for a real system.

Fence writes using a durable authority/lease and infrastructure controls; revoke old connections/credentials where needed. Validate that original and refund commands cannot be accepted concurrently in isolated regions. Record all failover decisions and require explicit approval for material settlement operations during degraded mode.

## Recovery exercise

1. Establish a known synthetic transaction/journal/outbox/receipt population and checksums.
2. Inject database-region, broker and network-partition failures independently.
3. Measure detection, fencing, promotion, routing and application readiness times.
4. Verify no duplicate financial instruction, no orphan journal and no unbalanced financial event.
5. Verify outbox replay and analytics catch-up, including duplicated transport records.
6. Reconcile external evidence and quantify any acknowledged-write loss against the proposed RPO.
7. Practice failback without two writers and preserve an incident timeline.

A successful diagram is not a successful recovery. Budget, staffing, latency, consistency, compliance and tested operating procedures determine whether such a design is appropriate.
