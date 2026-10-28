package com.example.practice.onboarding.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "status_history")
public class StatusHistory {
    @Id
    private UUID id;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "case_id", nullable = false)
    private OnboardingCase onboardingCase;
    @Enumerated(EnumType.STRING)
    @Column(name = "previous_status", length = 30)
    private CaseStatus previousStatus;
    @Enumerated(EnumType.STRING)
    @Column(name = "new_status", nullable = false, length = 30)
    private CaseStatus newStatus;
    @Column(nullable = false, length = 500)
    private String reason;
    @Column(name = "changed_at", nullable = false, updatable = false)
    private Instant changedAt;

    protected StatusHistory() { }

    public StatusHistory(OnboardingCase onboardingCase, CaseStatus from, CaseStatus to,
            String reason, Instant now) {
        this.id = UUID.randomUUID();
        this.onboardingCase = onboardingCase;
        this.previousStatus = from;
        this.newStatus = to;
        this.reason = reason;
        this.changedAt = now;
    }

    public UUID getId() { return id; }
    public OnboardingCase getOnboardingCase() { return onboardingCase; }
    public CaseStatus getPreviousStatus() { return previousStatus; }
    public CaseStatus getNewStatus() { return newStatus; }
    public String getReason() { return reason; }
    public Instant getChangedAt() { return changedAt; }
}
