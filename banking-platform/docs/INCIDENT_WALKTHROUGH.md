# Authorization timeout incident exercise

This is a synthetic local failure exercise. It is not an account of a real bank incident or a measured production outage.

## Symptom and first response

An analyst observes rising authorization latency and more HTTP 503 results. A failed authorization command rolls back its local transitions; an instruction that began `RECEIVED` remains `RECEIVED`. The useful first question is which stage slowed: request admission, database locking, the external network, or downstream event reporting. Pause repeated manual submissions and retain the original transaction UUID/idempotency key; generating fresh keys can create a duplicate business instruction.

Look at request-duration percentiles, authorization success/failure rates, network request duration/failure/retry counts, database pool/lock waits, outbox pending/oldest age and consumer lag. Acceptance latency and authorization latency are separate SLIs. A Kafka backlog can explain stale analytics without explaining a slow synchronous network call.

## Reproduce locally

Configure the fictional mock to delay responses longer than the network client's read timeout:

```sh
MOCK_NETWORK_SCENARIO=timeout MOCK_NETWORK_FAILURES_BEFORE_SUCCESS=-1 \
  docker compose up -d --force-recreate mock-network
python3 scripts/demo_network_timeout.py
```

The Compose variable controls are local demo inputs. Inspect `/health`, request IDs and the network logs; never copy credentials or entire request bodies into incident notes. Reset with normal scenario and recreate the mock after the exercise. A mock restart loses its in-memory authorization cache, which is itself an educational limitation.

## Investigation path

1. Confirm scope: which operations, time range and currencies are affected? Does submission still succeed while authorization fails?
2. Correlate an API 503 with its safe `requestId`, transaction UUID and network attempt classification. No customer/account content is needed.
3. Confirm dependency health separately from endpoint availability. A mock `/health` success does not prove `/authorizations` meets its latency budget.
4. Inspect bounded retry behavior. Only transport errors, 429 and selected transient 5xx are eligible; permanent 4xx and malformed successful responses do not become infinite retries. Respect bounded `Retry-After`.
5. Check the configured connect/read budgets and maximum attempts. Retries increase total elapsed time and dependency load. A bounded per-attempt timeout is not automatically a strict end-to-end deadline.
6. Look up the stable downstream transaction reference. The mock stores its decision before delaying a timeout response to demonstrate that the remote action may already exist.
7. Confirm local state, journals and history. A failed authorization command must not leave a captured payment or partial journal.
8. Restore dependency behavior, retry using the same stable identity, and verify one decision and one financial progression. Then reconcile independent evidence.

## Likely root cause and remediation

In this controlled exercise, a delay configured at the mock exceeds `NETWORK_READ_TIMEOUT_SECONDS`; retry volume magnifies latency. The request timing out does not prove the network rejected or ignored it. The safe mitigation is to reduce incoming work/repeated attempts, retain identity, restore dependency behavior and check its lookup/evidence. Raising timeouts blindly may exhaust connection pools and hold transaction row locks longer.

Long-term options include an end-to-end deadline, jittered bounded retries, dependency-specific concurrency limits, load shedding, a standard circuit breaker after measurement, a durable asynchronous authorization process and provider lookup/reconciliation. This project implements bounded retry and failure evidence; it does not claim all resilience patterns are present. A bulkhead separates capacity pools; backpressure limits production to sustainable consumption; a circuit breaker temporarily stops known-failing calls. These solve different problems.

## Example SLO exercise

Possible design targets are 99.95% acceptance availability, p95 acceptance latency below 250 ms, and 99.9% event delivery within 60 seconds. These are **fictional targets, not measured guarantees**. Define the denominator, eligible requests, observation window and exclusions before calculating an error budget. For 99.95% availability over 30 days, an all-time budget is about 21.6 minutes; request-based budgets use request counts instead. Percentiles need a histogram/window, not averages. Measure saturation, throughput and lock waits alongside latency before concluding the service needs more replicas.

## Incident record

Record symptom, impact scope, detection signal, timeline with timezone, correlated IDs, tested hypotheses, identified cause, mitigation evidence and owner/due date for permanent fixes. “Restarted the service” is an action, not a root cause. Preserve mismatch and history records; an incident write-up should explain why controls prevented or exposed financial inconsistency.
