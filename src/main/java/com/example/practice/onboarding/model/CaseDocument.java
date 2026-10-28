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
import jakarta.persistence.UniqueConstraint;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "case_document", uniqueConstraints = @UniqueConstraint(
        name = "uk_document_case_type", columnNames = {"case_id", "document_type"}))
public class CaseDocument {
    @Id
    private UUID id;
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "case_id", nullable = false)
    private OnboardingCase onboardingCase;
    @Enumerated(EnumType.STRING)
    @Column(name = "document_type", nullable = false, length = 30)
    private DocumentType documentType;
    @Column(name = "document_reference", nullable = false, length = 100)
    private String reference;
    @Column(nullable = false, length = 20)
    private String status;
    @Column(name = "submitted_at", nullable = false, updatable = false)
    private Instant submittedAt;

    protected CaseDocument() { }

    public CaseDocument(OnboardingCase onboardingCase, DocumentType type, String reference, Instant now) {
        this.id = UUID.randomUUID();
        this.onboardingCase = onboardingCase;
        this.documentType = type;
        this.reference = reference;
        this.status = "RECEIVED";
        this.submittedAt = now;
    }

    public UUID getId() { return id; }
    public OnboardingCase getOnboardingCase() { return onboardingCase; }
    public DocumentType getDocumentType() { return documentType; }
    public String getReference() { return reference; }
    public String getStatus() { return status; }
    public Instant getSubmittedAt() { return submittedAt; }
}
