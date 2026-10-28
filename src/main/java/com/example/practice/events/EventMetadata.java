package com.example.practice.events;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** An explicit allowlist prevents accidentally publishing applicant or document contents. */
final class EventMetadata {
    private static final Set<String> EVENT_TYPES = Set.of(
            "OnboardingCaseCreated", "DocumentSubmitted", "OnboardingStatusChanged", "OnboardingCompleted");
    private static final Set<String> STATUSES = Set.of(
            "CREATED", "DOCUMENTS_PENDING", "UNDER_REVIEW", "RISK_REVIEW", "APPROVED", "REJECTED", "COMPLETED");
    private static final Set<String> RISK_LEVELS = Set.of("LOW", "MEDIUM", "HIGH", "NOT_SCREENED");
    private static final Set<String> DOCUMENT_TYPES = Set.of("IDENTITY_PROOF", "ADDRESS_PROOF");

    private EventMetadata() {
    }

    static DomainEvent validate(DomainEvent event) {
        if (event == null || event.eventId() == null || event.caseId() == null || event.occurredAt() == null
                || event.eventType() == null
                || event.schemaVersion() != 1 || !EVENT_TYPES.contains(event.eventType()) || event.payload() == null) {
            throw new InvalidDomainEventException("Unsupported domain event envelope");
        }
        return new DomainEvent(event.eventId(), event.eventType(), event.caseId(), event.occurredAt(),
                event.schemaVersion(), sanitize(event.payload()));
    }

    static Map<String, Object> sanitize(Map<String, Object> payload) {
        Map<String, Object> metadata = new LinkedHashMap<>();
        payload.forEach((key, value) -> {
            if (key == null || value == null) {
                throw new InvalidDomainEventException("Event metadata must not contain null values");
            }
            String text = value.toString();
            boolean valid = switch (key) {
                case "applicantId", "documentId" -> isUuid(text);
                case "documentType" -> DOCUMENT_TYPES.contains(text);
                case "status", "previousStatus", "newStatus" -> STATUSES.contains(text);
                case "riskLevel" -> RISK_LEVELS.contains(text);
                default -> false;
            };
            if (!valid) {
                // Do not include the rejected value or key in logs/errors.
                throw new InvalidDomainEventException("Unsupported event metadata");
            }
            metadata.put(key, text);
        });
        return Map.copyOf(metadata);
    }

    private static boolean isUuid(String value) {
        try {
            return UUID.fromString(value).toString().equalsIgnoreCase(value);
        } catch (IllegalArgumentException exception) {
            return false;
        }
    }
}
