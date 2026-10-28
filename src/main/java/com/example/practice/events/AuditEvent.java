package com.example.practice.events;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.PostLoad;
import jakarta.persistence.PostPersist;
import jakarta.persistence.Table;
import jakarta.persistence.Transient;
import java.time.Instant;
import java.util.UUID;
import org.springframework.data.domain.Persistable;

/** Durable inbox/audit record; no applicant names, email or document reference is retained. */
@Entity
@Table(name = "onboarding_audit_event")
public class AuditEvent implements Persistable<UUID> {
    @Id
    @Column(name = "event_id")
    private UUID eventId;

    @Column(name = "case_id", nullable = false)
    private UUID caseId;

    @Column(name = "event_type", nullable = false, length = 80)
    private String eventType;

    @Column(name = "occurred_at", nullable = false)
    private Instant occurredAt;

    @Column(name = "received_at", nullable = false)
    private Instant receivedAt;

    @Column(name = "payload_hash", nullable = false, length = 64)
    private String payloadHash;

    @Transient
    private boolean newRecord = true;

    protected AuditEvent() {
    }

    AuditEvent(DomainEvent event, String payloadHash) {
        this.eventId = event.eventId();
        this.caseId = event.caseId();
        this.eventType = event.eventType();
        this.occurredAt = event.occurredAt();
        this.receivedAt = Instant.now();
        this.payloadHash = payloadHash;
    }

    @Override
    public UUID getId() {
        return eventId;
    }

    @Override
    public boolean isNew() {
        return newRecord;
    }

    @PostLoad
    @PostPersist
    void markNotNew() {
        this.newRecord = false;
    }

    public UUID getEventId() { return eventId; }
    public UUID getCaseId() { return caseId; }
    public String getEventType() { return eventType; }
    public Instant getOccurredAt() { return occurredAt; }
    public Instant getReceivedAt() { return receivedAt; }
    public String getPayloadHash() { return payloadHash; }
}
