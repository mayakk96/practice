package com.example.practice.onboarding.model;

import com.example.practice.screening.RiskLevel;
import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.FetchType;
import jakarta.persistence.Id;
import jakarta.persistence.JoinColumn;
import jakarta.persistence.ManyToOne;
import jakarta.persistence.Table;
import jakarta.persistence.Version;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "onboarding_case")
public class OnboardingCase {
    @Id
    private UUID id;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "applicant_id", nullable = false)
    private Applicant applicant;
    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 30)
    private CaseStatus status;
    @Enumerated(EnumType.STRING)
    @Column(name = "risk_level", nullable = false, length = 20)
    private RiskLevel riskLevel;
    @Column(name = "assigned_team", nullable = false, length = 40)
    private String assignedTeam;
    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;
    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;
    @Version
    @Column(nullable = false)
    private long version;

    protected OnboardingCase() { }

    public OnboardingCase(Applicant applicant, String assignedTeam, Instant now) {
        this.id = UUID.randomUUID();
        this.applicant = applicant;
        this.status = CaseStatus.CREATED;
        this.riskLevel = RiskLevel.NOT_SCREENED;
        this.assignedTeam = assignedTeam;
        this.createdAt = now;
        this.updatedAt = now;
    }

    public void transitionTo(CaseStatus target, RiskLevel risk, Instant now) {
        this.status = target;
        this.riskLevel = risk;
        this.updatedAt = now;
    }

    public void touch(Instant now) { this.updatedAt = now; }
    public UUID getId() { return id; }
    public Applicant getApplicant() { return applicant; }
    public CaseStatus getStatus() { return status; }
    public RiskLevel getRiskLevel() { return riskLevel; }
    public String getAssignedTeam() { return assignedTeam; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getUpdatedAt() { return updatedAt; }
    public long getVersion() { return version; }
}
