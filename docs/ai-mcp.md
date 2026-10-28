# Read-only MCP and a foundational policy RAG pipeline

This is a fictional educational application. The policy files are invented examples, not BNY policy, legal guidance, or a real onboarding/risk decision system. The ordinary service layer enforces the workflow; an AI answer never changes a case.

## Dependency choice and compatibility

The implementation uses `org.springframework.ai:spring-ai-starter-mcp-server-webmvc:1.1.8` and its supported MCP Java SDK integration. Before choosing it, we checked Maven Central release metadata, the published dependency POMs, the official Spring AI `1.1.x` source POM, and the official MCP starter/annotation reference. Spring AI's 1.1 line uses Spring Boot 3.5; the repository keeps Boot 3.5.16. The newer Spring AI 2.x line belongs to the Boot 4 generation and was deliberately not mixed into this project.

References used:

- [Spring AI 1.1.x parent and compatibility dependencies](https://github.com/spring-projects/spring-ai/blob/1.1.x/pom.xml)
- [Official MCP starter reference](https://github.com/spring-projects/spring-ai/blob/1.1.x/spring-ai-docs/src/main/antora/modules/ROOT/pages/api/mcp/mcp-server-boot-starter-docs.adoc)
- [Official stateless WebMVC transport reference](https://github.com/spring-projects/spring-ai/blob/1.1.x/spring-ai-docs/src/main/antora/modules/ROOT/pages/api/mcp/mcp-stateless-server-boot-starter-docs.adoc)
- [Published starter release metadata](https://repo.maven.apache.org/maven2/org/springframework/ai/spring-ai-starter-mcp-server-webmvc/maven-metadata.xml)

Versions are pinned through the Spring AI BOM in `pom.xml`; they are not downloaded dynamically at application startup. Compatibility checks should be repeated when upgrading either framework.

## REST, an API wrapper, and MCP solve different problems

| Component | Responsibility in this repository |
| --- | --- |
| REST controller | Maps HTTP requests/status codes and validated JSON DTOs to application operations. |
| API wrapper | Encapsulates a downstream service's HTTP protocol, serialization, timeouts, retries, and error translation. See `screening/`. |
| MCP server/tool | Advertises typed capabilities to MCP clients and adapts a safe subset of operations to application services. |

MCP does not replace the service, repository, database, or REST API. A second transport should reuse those layers, not grow a second version of business logic.

```text
MCP client
    | JSON-RPC over stateless HTTP, /mcp
Spring AI / MCP Java SDK
    |
OnboardingTools (validation and sanitization)
    |                           |
OnboardingService          KnowledgeService
    |                           |
Repositories / PostgreSQL   bundled policy index / answer-model interface
```

`@McpTool` and `@McpToolParam` create the tool declarations and JSON input schemas. This is an actual MCP transport managed by the supported SDK, not an ordinary REST endpoint merely named MCP. `McpProtocolIntegrationTest` exercises initialization, tool discovery, successful calls, invalid calls, and structured results over a real local HTTP socket.

The server is synchronous and stateless. Clients can initialize and discover tools, but this example does not retain conversation sessions, ask clients to sample a model, or expose server-to-client filesystem access.

## Tools and safety boundary

| Tool | Inputs | Output |
| --- | --- | --- |
| `get_onboarding_case` | Canonical case UUID | ID, status, risk level, creation/update times. |
| `list_pending_cases` | Page 0..10000, size 1..50 | A bounded page of non-terminal case metadata, selected by the application service's database query. |
| `get_case_status_history` | Canonical case UUID | Status transitions and timestamps, up to 100 entries. |
| `search_onboarding_policy` | Nonblank question up to 500 characters; topK 1..5 | Policy evidence, a supported demo/model answer, citations, and implementation names. |

The case tools omit applicant names, email addresses, document references, team names, and free-text history reasons. Tools cannot create cases, upload documents, approve applicants, change statuses, run arbitrary SQL, or fetch arbitrary URLs. The model endpoint is configured by the operator, not by tool input.

The handlers return MCP `CallToolResult` with both readable content and `structuredContent`. Invalid UUIDs, excessive page sizes, missing cases, and model failures return `isError=true` plus stable sanitized codes such as `INVALID_INPUT`, `NOT_FOUND`, or `MODEL_UNAVAILABLE`. They never return database exception text, provider response bodies, credentials, or user input inside an error message.

Read-only/idempotent MCP annotation hints describe behavior; they are not authorization. The application's HTTP security configuration protects the `/mcp` transport when development authentication is enabled. A real deployment would additionally require authenticated client identities, OAuth/OIDC integration where appropriate, per-tool and per-case scopes, tenant filtering in the service/repository layer, rate limits, and auditable access. Knowing a case UUID is not sufficient authorization in a real system.

MCP resources are URI-addressed context data selected by a client; tools are named operations invoked with arguments. This project exposes tools and keeps unused MCP capabilities disabled rather than adding decorative resources or prompts.

## Try the MCP protocol

For the no-credential local demo, start with `./mvnw spring-boot:run -Dspring-boot.run.profiles=demo`. With the application running locally, initialize the stateless server:

```sh
curl -sS http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"local-study-client","version":"1.0"}}}'
```

Discover tools:

```sh
curl -sS http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

Search fictional policy:

```sh
curl -sS http://localhost:8080/mcp \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -H 'MCP-Protocol-Version: 2025-06-18' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"search_onboarding_policy","arguments":{"query":"Which documents are required for approval?","topK":2}}}'
```

When authentication is enabled, add the configured read-only user's Basic authentication credentials locally. Do not put credentials into committed scripts or terminal output shared with others. The transport can represent JSON-RPC responses as JSON or SSE according to negotiated headers; a general MCP client should use the SDK rather than treat this as an arbitrary REST response.

## RAG pipeline

Retrieval-augmented generation retrieves relevant evidence before asking an answer model to respond. Retrieval supplies domain information that the model may not know, makes the source inspectable, and reduces the need to place an entire document collection into every prompt. It does not guarantee correctness.

```text
resources/knowledge/*.txt
    -> PolicyDocumentLoader: ingest text and chunk it
    -> HashingEmbeddingModel: convert chunks to numeric vectors
    -> PolicyVectorIndex: retain an immutable in-memory index

question
    -> same embedding model
    -> cosine similarity / bounded top-K retrieval
    -> KnowledgeService: build a bounded source-labelled context
    -> PolicyAnswerModel: deterministic demo or configured HTTP model
    -> answer + evidence citations + explicit implementation names
```

The four bundled documents describe fictional approval, risk screening, privacy/audit, and idempotency/event policies. The loader reads classpath resources, including resources packaged inside the executable JAR. It makes 80-word chunks with 15-word overlap. Chunk identifiers include the source filename and sequence number. Overlap reduces the chance that a useful statement is split exactly at a boundary; it can also produce redundant retrieval results.

### Embeddings and retrieval

The default embedding implementation uses **512-dimensional normalized signed feature hashing of word tokens**. Queries and chunks are embedded by the same algorithm, and retrieval ranks cosine similarity, rejecting scores below 0.12. This is a real numeric vector representation and similarity calculation; it is not a pretrained semantic embedding model. It mainly matches shared words, has hash collisions, uses simple English-oriented tokenization, and does not understand synonyms or financial terminology. The dimensions and threshold are small educational choices, not a quality claim.

`EmbeddingModel` is an interface. A production or further-study extension can replace feature hashing with a trained local or hosted embedding provider, rebuild the index using the same provider, and evaluate retrieval against a labelled question set. Existing document vectors and query vectors must use the same embedding space and dimensions. An external vector database is unnecessary for four static documents; it becomes useful for a larger changing corpus, persisted indexes, filtering, and scalable nearest-neighbour search.

### Context and answer model

The REST request is:

```sh
curl -sS http://localhost:8080/api/knowledge/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"Which documents are required for approval?","topK":2}'
```

The response contains `answer`, `grounded`, `embeddingModel`, `answerModel`, and `citations`. Every citation includes a source, chunk ID, excerpt, and retrieval score. `grounded=true` means retrieved evidence was supplied to the answer step; it is **not** a model faithfulness score or proof that every generated claim is supported. Inspect the evidence.

The selected evidence context is capped at 6,000 characters, the request at 500 characters, and topK at five. Bounds keep memory, latency, and potential external model cost understandable. Real token budgeting depends on the selected model tokenizer; character limits are only a conservative demonstration.

The default `DeterministicPolicyAnswerModel` returns source-labelled excerpts. It is an offline deterministic test/demo implementation, **not an LLM**, and does not call a paid service. This makes the pipeline studyable and the test suite reproducible without credentials. No model call is made when retrieval returns no evidence; the service instead says the bundled policies do not contain an answer.

The optional `HttpPolicyAnswerModel` makes a real bounded OpenAI-compatible `/chat/completions` request through Spring `RestClient`. Its system instruction restricts the response to supplied evidence and asks for source citations. It sends only the question and fictional policy context, not applicant records. It is configured through environment variables:

```sh
export APPLICATION_KNOWLEDGE_MODE=http
export APPLICATION_KNOWLEDGE_BASE_URL=http://localhost:11434/v1
export APPLICATION_KNOWLEDGE_MODEL=your-installed-model-name
# If your chosen provider requires a key, set APPLICATION_KNOWLEDGE_API_KEY securely in your shell/environment.
./mvnw spring-boot:run -Dspring-boot.run.profiles=demo
```

This example assumes a separately installed OpenAI-compatible local model server with that model available. The repository does not install or download a large model. Use your provider's HTTPS base URL for a hosted model. Credentials are prohibited over plaintext HTTP except for loopback development endpoints; redirects are disabled so an Authorization header cannot follow a redirect to an unexpected host. Connect/read timeouts default to one/five seconds and have upper bounds. The adapter does not retry model requests automatically, which avoids accidental duplicate billing. Non-success responses, missing model answers, or oversized answers become a sanitized availability error.

### Retrieval failure, hallucination, and prompt injection

- **Retrieval failure:** no useful evidence is returned, or the best matches are irrelevant. Fix ingestion, chunking, embedding quality, retrieval thresholds, corpus coverage, or query handling; a larger generation model alone does not fix missing evidence.
- **Hallucination:** a generation model produces an unsupported claim despite receiving relevant context. Evaluate answer faithfulness, constrain generation, verify claims/citations, or abstain. A retrieval score is not confidence in an answer.
- **Prompt injection:** documents and questions can contain instructions that conflict with the application role. The HTTP adapter marks them as untrusted data and keeps instructions separate, but prompting alone is not a security boundary. The decisive boundary here is that no model has tools that mutate cases, access secrets, or retrieve arbitrary URLs. The demo corpus is trusted bundled sample data; untrusted ingestion would require additional controls and testing.

Never submit real personal data, confidential company documents, or credentials as policy queries. This prototype is unsuitable for real eligibility, identity, regulatory, legal, or credit decisions. Semantic retrieval, document versioning, authorization-aware retrieval, quality evaluation, citation validation, cost limits, and human review would require further engineering.

## Tests and useful interview explanations

- `PolicyRetrievalTest`: ingestion, overlapping chunks, deterministic normalized embeddings, cosine calculations, relevant source ranking, bounded context, abstention, and input validation.
- `HttpPolicyAnswerModelTest`: a mocked downstream verifies endpoint/headers/serialization, bounded generation parameters, error sanitization, and malformed response handling.
- `KnowledgeHttpIntegrationTest`: application HTTP validation and a complete offline evidence-based response.
- `OnboardingToolsTest`: service delegation, bounded queries, PII/free-text exclusion, and predictable sanitized errors.
- `McpProtocolIntegrationTest`: real MCP initialization, tool discovery, input schemas/read-only hints, JSON-RPC calls, structured outputs, and error flags over HTTP.

Be able to explain why the pipeline can run without an LLM key, why a hash embedding is weaker than a trained semantic embedding, why MCP is a transport adapter rather than a second business layer, why tool hints are not authorization, and why retrieved context reduces but does not eliminate hallucination.
