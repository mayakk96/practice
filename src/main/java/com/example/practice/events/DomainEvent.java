package com.example.practice.events;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/** Versioned transport envelope. Payload contains identifiers and enum metadata only. */
public record DomainEvent(
        UUID eventId,
        String eventType,
        UUID caseId,
        Instant occurredAt,
        int schemaVersion,
        Map<String, Object> payload) {
}
