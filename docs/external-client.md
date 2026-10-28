# External risk-screening boundary

`RiskScreeningClient` is a business interface: `screen(caseId)` returns a `ScreeningResult`.
The onboarding service knows about risk levels and application exceptions, not URLs,
JSON serialization, status codes, headers, or transport retries. `HttpRiskScreeningClient`
owns those provider details. A future provider can implement the same interface without
changing the workflow controller.

The provider is fictional. Only an opaque case UUID leaves the application. Applicant
names, email addresses, document references, and reasons are never sent to it or logged
by this integration. The sample provider is a separate local Python HTTP service with no
third-party dependencies.

## Modes and configuration

The default `stub` mode returns deterministic `LOW` risk. It is explicitly a local stub,
not a successful call to an actual screening institution. Docker Compose selects `http`
mode and calls the separate `mock-risk` service.

| Property | Default | Constraint / purpose |
| --- | --- | --- |
| `application.screening.mode` | `stub` | `stub` or `http` |
| `application.screening.base-url` | `http://localhost:8090` | HTTP(S), no URL credentials/query/fragment |
| `application.screening.connect-timeout` | `500ms` | Positive, at most 5 seconds |
| `application.screening.read-timeout` | `1s` | Positive, at most 10 seconds |
| `application.screening.max-attempts` | `3` | 1–3, including the first attempt |
| `application.screening.backoff` | `100ms` | 0–1 second |

Spring Boot environment binding supports, for example,
`APPLICATION_SCREENING_MODE=http` and
`APPLICATION_SCREENING_BASE_URL=http://mock-risk:8090`.
The JDK HTTP transport has explicit connection and request/read deadlines. It does not
follow redirects. TLS verification stays enabled; production credentials would require
a secure secret binding and an authenticated provider contract.

## Wire contract

```http
POST /screenings
Content-Type: application/json
Accept: application/json
Idempotency-Key: 063c796a-4345-4e2d-a496-0c9ed00a8dc6
User-Agent: enterprise-onboarding-portfolio/1.0
X-Request-ID: optional-validated-correlation-id

{"caseId":"063c796a-4345-4e2d-a496-0c9ed00a8dc6"}
```

```json
{"riskLevel":"LOW","providerReference":"demo-063c796a-4345-4e2d-a496-0c9ed00a8dc6"}
```

The response must contain a real assessment (`LOW`, `MEDIUM`, or `HIGH`) and a bounded,
simple provider reference. Missing fields, unknown risk levels, `NOT_SCREENED`, invalid
references, and unreadable JSON are provider protocol failures. An HTTP 200 alone does
not establish a usable assessment.

The wrapper uses Jackson to serialize the typed request, then a Spring HTTP interceptor
sets the exact `Content-Length` of those serialized bytes. This supports the small mock
provider's bounded, fixed-length request contract without manually constructing JSON or
implementing an HTTP chunk decoder. The provider returns 411 when length is absent.
A real loopback test requires `Content-Length`, rejects chunked requests, and checks the
received JSON and idempotency key; a mock request factory alone would not catch framing
differences in the actual JDK HTTP transport.

## Retry and error policy

| Outcome | Action |
| --- | --- |
| Valid response | Return the assessment |
| Network/connection/read failure | Retry within the attempt budget |
| HTTP 5xx | Retry within the attempt budget |
| HTTP 429 | Retry only when its retry delay fits the synchronous budget |
| Other HTTP 4xx, including 400/401/403/404/422 | Do not retry; translate to a provider-rejection exception |
| Malformed or invalid provider response | Do not retry; translate to a protocol exception |
| Thread interruption | Preserve the interrupted flag and stop work |

Without a `Retry-After` header, backoff is exponential: with default settings the waits
are 100 ms and 200 ms. An individual wait is capped at one second. Both integer and
HTTP-date `Retry-After` values are understood. A provider asking for more than one second
is not called prematurely: the wrapper fails fast so the caller can try again later.
The wrapper never sleeps for an arbitrary provider-supplied duration.

Exhausted transient failures become `ScreeningUnavailableException` (application HTTP
503). Permanent request/protocol failures become `ScreeningRejectedException`
(application HTTP 502). The original provider response body is discarded rather than
put in a translated exception, response, or log. Logs contain opaque case IDs, attempt
counts, technical failure categories, and bounded delays. Spring Boot's configured
`RestClient.Builder` also supplies HTTP client observations when Actuator is present.

Default retry work is bounded by three transport attempts and 300 ms of backoff. A
conservative connection-plus-request upper estimate is about 4.8 seconds with the
default deadlines. This bounds the database lock held during an approval attempt;
at larger scale, an asynchronous screening state would avoid holding a transaction
open during network work.

## Idempotency and transaction boundaries

Retries of a POST are safe only if the provider treats the operation as idempotent.
Every attempt for the same case carries the same `Idempotency-Key`, including later
approval attempts after a timeout. The fictional provider caches one assessment per
case. It rejects a key that does not match the case ID. It returns the same assessment
on repeats; a timeout after a provider accepted work does not cause a second logical
screening.

That contract is separate from the platform's case-creation `Idempotency-Key` handling.
The mock's cache is process-local and disappears on restart, so this provider is a demo,
not an example of durable financial-grade provider deduplication. A real integration
would agree key retention, payload fingerprints, authentication, reconciliation, and
reassessment versions with the provider. A fresh assessment after changing facts would
need a distinct versioned key rather than reusing this one-assessment-per-case example.

Provider calls cannot participate atomically in the application's database transaction.
The application checks screening before it saves approval. Provider failure leaves the
workflow status unchanged, while an already-completed external assessment can safely
be retrieved by the same key on a later attempt.

## Run and test the provider

Docker Compose builds `demo/risk-service/Dockerfile` and exposes the service only inside
the Compose network. To run the provider independently for study:

```sh
python3 demo/risk-service/server.py
```

It listens on port 8090 and supplies `GET /health`. Only fictional IDs should be used.
Optional environment variables allow controlled local failure scenarios:

| Variable | Default | Behavior |
| --- | --- | --- |
| `MOCK_RISK_LEVEL` | `LOW` | Return LOW, MEDIUM, or HIGH for new case IDs |
| `MOCK_RISK_FAILURES_BEFORE_SUCCESS` | `0` | Return 503 on the first 0–10 attempts per new case ID |
| `MOCK_RISK_DELAY_MS` | `0` | Delay responses by 0–10,000 ms to demonstrate client timeouts |

```sh
MOCK_RISK_FAILURES_BEFORE_SUCCESS=2 python3 demo/risk-service/server.py
python3 -m unittest discover -s demo/risk-service -p 'test_*.py' -v
```

The Java test suite uses `MockRestServiceServer` to assert serialization, headers,
stable retry keys, status classification, exponential backoff, `Retry-After`, privacy,
and interruption. Separate tests use real loopback HTTP sockets to demonstrate an actual
read timeout and connection refusal. They require neither the Python service nor a
paid external API. The Python tests prove health, request validation, simulated failure,
and duplicate response behavior in the local provider itself.

## Interview explanation

“The API wrapper gives the business layer one typed contract. I configure timeouts once,
keep serialization and authentication concerns in one place, and translate provider
failures into exceptions the application understands. Retry behavior is consistent and
tested instead of repeated differently in every controller. I only retry operations
whose idempotency contract makes repeat calls safe, and I keep a bounded latency budget.”
