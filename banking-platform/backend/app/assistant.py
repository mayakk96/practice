"""Read-only, deterministic incident evidence. No financial commands or model tool calls."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter

from app.knowledge import KnowledgeService, get_knowledge_service

RESULT_FIELDS = (
    "id",
    "runId",
    "transactionId",
    "classifications",
    "internalAmountMinor",
    "externalAmountMinor",
    "currency",
    "varianceMinor",
    "internalStatus",
    "externalStatus",
    "internalBusinessDate",
    "externalBusinessDate",
)
RUN_FIELDS = (
    "id",
    "businessDate",
    "currency",
    "recordsProcessed",
    "recordsMatched",
    "recordsUnmatched",
    "totalInternalMinor",
    "totalExternalMinor",
    "varianceMinor",
    "status",
    "startedAt",
    "completedAt",
)
EXCEPTION_FIELDS = (
    "id",
    "transactionId",
    "reconciliationRunId",
    "reconciliationResultId",
    "category",
    "severity",
    "status",
    "version",
    "createdAt",
    "updatedAt",
)
TRANSACTION_FIELDS = (
    "id",
    "transactionType",
    "amountMinor",
    "currency",
    "status",
    "businessDate",
    "version",
    "createdAt",
    "updatedAt",
)


def select_fields(record: dict, fields: tuple[str, ...]) -> dict:
    """An allowlist keeps free-text reasons, names, account and network references out of AI evidence."""
    return {key: record[key] for key in fields if key in record}


class IncidentAssistantService:
    def __init__(
        self,
        factory=None,
        *,
        exceptions=None,
        reconciliation=None,
        transactions=None,
        knowledge: KnowledgeService | None = None,
    ):
        # Late imports avoid coupling migration discovery to HTTP/model adapters.
        if exceptions is None:
            from app.exceptions import OperationalExceptionService

            exceptions = (
                OperationalExceptionService() if factory is None else OperationalExceptionService(factory)
            )
        if reconciliation is None:
            from app.reconciliation import ReconciliationService

            reconciliation = ReconciliationService() if factory is None else ReconciliationService(factory)
        if transactions is None:
            from app.transactions import TransactionService

            transactions = TransactionService() if factory is None else TransactionService(factory)
        self.exceptions = exceptions
        self.reconciliation = reconciliation
        self.transactions = transactions
        self.knowledge = knowledge or get_knowledge_service()

    def explain(self, exception_id: UUID) -> dict:
        exception = self.exceptions.get(exception_id)
        result_id = exception.get("reconciliationResultId")
        run_id = exception.get("reconciliationRunId")
        result = self.reconciliation.get_result(UUID(str(result_id))) if result_id else None
        run = self.reconciliation.get_run(UUID(str(run_id))) if run_id else None
        transaction_id = exception.get("transactionId") or (result or {}).get("transactionId")
        transaction = self.transactions.get(UUID(str(transaction_id))) if transaction_id else None
        classifications = (result or {}).get("classifications", [])
        if not classifications:
            classifications = ["UNCLASSIFIED"]
        possible_causes = [self._possible_cause(str(item)) for item in classifications]
        citations = self.knowledge.retrieve(
            "reconciliation settlement variance "
            + " ".join(str(item).replace("_", " ").lower() for item in classifications),
            3,
        )
        evidence = {"operationalException": select_fields(exception, EXCEPTION_FIELDS)}
        if result:
            evidence["reconciliationSnapshot"] = select_fields(result, RESULT_FIELDS)
        if run:
            evidence["reconciliationRun"] = select_fields(run, RUN_FIELDS)
        if transaction:
            evidence["transactionCurrentState"] = select_fields(transaction, TRANSACTION_FIELDS)
        return {
            "generationMode": "deterministic-read-only-evidence",
            "readOnly": True,
            "observedCondition": {
                "exceptionId": str(exception_id),
                "exceptionStatus": exception.get("status"),
                "classifications": classifications,
                "currency": (result or run or {}).get("currency"),
                "varianceMinor": (result or run or {}).get("varianceMinor"),
            },
            "possibleCauses": possible_causes,
            "supportingTransactionIds": [str(transaction_id)] if transaction_id else [],
            "reconciliationResultIds": [str(result_id)] if result_id else [],
            "evidence": evidence,
            "suggestedInvestigationSteps": [
                "Compare the immutable reconciliation snapshot with the original external evidence for this date and currency.",
                "Inspect the listed transaction IDs and status history; current state may differ from the run snapshot.",
                "Check duplicate references, import timing, currency, signs and downstream confirmations before establishing a root cause.",
                "Preserve the original run. Correct the evidence through an authorized operator procedure and rerun reconciliation.",
                "Record investigation notes through the operator exception workflow; resolution itself does not change financial data.",
            ],
            "citations": citations,
            "financialActionsPerformed": [],
        }

    @staticmethod
    def _possible_cause(classification: str) -> str:
        causes = {
            "AMOUNT_MISMATCH": "The snapshot amounts differ. A source-data error, sign convention or external adjustment is a hypothesis until the original records are checked.",
            "CURRENCY_MISMATCH": "The external and internal currencies differ. Check record mapping; never convert or add currencies implicitly.",
            "STATUS_MISMATCH": "The recorded processing states differ. Inspect lifecycle history and external confirmation timing.",
            "MISSING_EXTERNAL": "No corresponding external evidence was present in this run. Delayed or incomplete delivery is possible.",
            "MISSING_INTERNAL": "External evidence has no corresponding internal transaction in this run. Check the reference and ingestion path.",
            "UNKNOWN_REFERENCE": "The external reference could not be linked to an internal transaction. Verify the source reference without creating a payment automatically.",
            "DUPLICATE_EXTERNAL": "More than one external row uses the reference. Check duplicate file delivery and source identifiers before resubmission.",
            "DUPLICATE_INTERNAL": "More than one internal candidate was reported. Investigate the matching key and uniqueness controls.",
            "LATE_ARRIVAL": "The evidence arrived outside the expected business-date window. Verify timestamps and rerun using corrected evidence.",
            "SETTLEMENT_VARIANCE": "The aggregate settlement totals differ. Inspect the individual mismatches to explain the signed variance.",
            "MATCHED": "The snapshot values match. Check why a separate operational exception remains open.",
        }
        return causes.get(
            classification,
            "The available structured evidence does not establish a cause. Review the linked records and runbook with an operator.",
        )


router = APIRouter(prefix="/api/assistant", tags=["Read-only incident assistance"])


@router.get("/exceptions/{exception_id}")
def explain_exception(exception_id: UUID) -> dict:
    return IncidentAssistantService().explain(exception_id)
