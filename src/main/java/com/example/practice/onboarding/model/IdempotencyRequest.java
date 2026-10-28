package com.example.practice.onboarding.model;

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

/**
 * A claim and its case commit together. Persistable forces INSERT for new assigned
 * keys: merge could otherwise overwrite a winner committed after an initial lookup.
 */
@Entity
@Table(name = "idempotency_request")
public class IdempotencyRequest implements Persistable<String> {
    @Id
    @Column(name = "request_key", length = 100)
    private String key;
    @Column(nullable = false, length = 64)
    private String fingerprint;
    @Column(name = "case_id")
    private UUID caseId;
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;
    @Transient
    private boolean newClaim = true;

    protected IdempotencyRequest() { }

    public IdempotencyRequest(String key, String fingerprint, Instant now) {
        this.key = key;
        this.fingerprint = fingerprint;
        this.createdAt = now;
    }

    public void complete(UUID caseId) { this.caseId = caseId; }
    @Override
    public String getId() { return key; }
    @Override
    public boolean isNew() { return newClaim; }
    @PostPersist
    @PostLoad
    private void persisted() { this.newClaim = false; }
    public String getKey() { return key; }
    public String getFingerprint() { return fingerprint; }
    public UUID getCaseId() { return caseId; }
    public Instant getCreatedAt() { return createdAt; }
}
