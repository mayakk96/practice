package com.example.practice.events;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "event_outbox")
public class OutboxEvent {
    @Id
    private UUID id;

    @Column(name = "sequence_number", insertable = false, updatable = false, nullable = false)
    private Long sequenceNumber;

    @Column(name = "case_id", nullable = false)
    private UUID caseId;

    @Column(name = "event_type", nullable = false, length = 80)
    private String eventType;

    @Column(name = "event_json", nullable = false, length = 12000)
    private String eventJson;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "published_at")
    private Instant publishedAt;

    @Column(nullable = false)
    private int attempts;

    @Column(name = "next_attempt_at", nullable = false)
    private Instant nextAttemptAt;

    @Column(name = "last_failure", length = 40)
    private String lastFailure;

    protected OutboxEvent() {
    }

    OutboxEvent(DomainEvent event, String eventJson) {
        this.id = event.eventId();
        this.caseId = event.caseId();
        this.eventType = event.eventType();
        this.eventJson = eventJson;
        this.createdAt = event.occurredAt();
        this.nextAttemptAt = event.occurredAt();
    }

    void delivered(Instant now) {
        this.attempts++;
        this.publishedAt = now;
        this.lastFailure = null;
    }

    void failed(Instant retryAt, String classification) {
        this.attempts++;
        this.nextAttemptAt = retryAt;
        this.lastFailure = classification;
    }

    public UUID getId() { return id; }
    public UUID getCaseId() { return caseId; }
    public String getEventType() { return eventType; }
    public String getEventJson() { return eventJson; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getPublishedAt() { return publishedAt; }
    public int getAttempts() { return attempts; }
    public Instant getNextAttemptAt() { return nextAttemptAt; }
    public String getLastFailure() { return lastFailure; }
}
