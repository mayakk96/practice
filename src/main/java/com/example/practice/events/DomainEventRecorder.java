package com.example.practice.events;

import java.util.Map;
import java.util.UUID;

/** Records an event in the same database transaction as its business change. */
public interface DomainEventRecorder {
    void record(String eventType, UUID caseId, Map<String, Object> payload);
}
