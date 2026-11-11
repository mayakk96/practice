# Read-only AI assistance and evidence boundaries

The AI use case is operational investigation: collect transaction, reconciliation and exception evidence, retrieve relevant synthetic runbook passages and help an analyst explain what is observed. It does not make an accounting decision or approve money movement. See [AI_SAFETY](AI_SAFETY.md) for the precise implemented transport/settings.

## Tools

`backend/app/mcp_server.py` uses the official MCP SDK and provides 11 read-only tools:

- `get_transaction`
- `find_transaction_by_external_reference`
- `list_failed_transactions`
- `get_transaction_history`
- `get_settlement_batch`
- `get_reconciliation_run`
- `list_reconciliation_mismatches`
- `list_open_exceptions`
- `get_daily_transaction_summary`
- `search_banking_runbooks`
- `explain_reconciliation_exception`

Tools delegate to existing service read methods. UUIDs, dates, currencies, query length, topK and pagination are validated/bounded. Output field allowlists omit customer display names, account references, network references, free-text reasons and resolution notes. Read-only annotations communicate intent, while the absence of mutation operations and HTTP authorization enforce it.

There are no tools to authorize/capture/settle/reverse/refund a payment, edit a ledger or resolve a material exception. A natural-language request or retrieved instruction cannot supply authority the tool server does not possess.

## Retrieval and generation

Synthetic files under `backend/app/runbooks/` are split into 80-word chunks with 15-word overlap. A 512-dimensional signed feature-hash vector supplies a deterministic lexical baseline. Actual lexical overlap and a relevance threshold guard against hash-only coincidence; top 5 and 6,000-character context limits bound evidence.

Default knowledge answers are deterministic extracts with citations and need no API key. Optional HTTP generation is separately configured with `KNOWLEDGE_MODE=http`, `KNOWLEDGE_MODEL_URL`, `KNOWLEDGE_MODEL` and optional `KNOWLEDGE_API_KEY`. Provider URLs require HTTPS except loopback educational services. It is disabled by default; no credential is bundled.

The incident endpoint `GET /api/assistant/exceptions/{id}` remains deterministic even if external knowledge generation is configured. `IncidentAssistantService.explain` assembles immutable mismatch/run evidence and current transaction state, explicitly distinguishing them. It returns observed condition, possible causes, supporting IDs, suggested human steps and citations. Current state can differ from the preserved run snapshot.

## Threat and evaluation model

A runbook or user query may contain malicious instructions. Treat the text as quoted evidence, never as authorization. Limiting context and omitting sensitive fields reduce exposure, but do not magically solve prompt injection. The stronger boundary is that model-facing code cannot execute financial mutations.

A citation proves only that a source passage was supplied. It does not prove the conclusion is true, that the source is current or that a proposed remediation is authorized. An amount difference supports an observed variance; it does not prove fraud, data loss or a network outage. The default assistant labels possible explanations as hypotheses.

Tests cover no-relevance behavior, chunk/context bounds, optional provider failure, real MCP handshake/tool list/call, privacy fields and adversarial requests without mutation tools. Production evaluation would add representative task relevance, supported-claim/citation scoring, adversarial corpora, access-controlled retrieval, provider privacy review and ongoing human feedback.
