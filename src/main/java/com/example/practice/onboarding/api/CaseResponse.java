package com.example.practice.onboarding.api;

import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.screening.RiskLevel;
import java.time.Instant;
import java.util.UUID;

public record CaseResponse(UUID id, UUID applicantId, String firstName, String lastName,
        String email, CaseStatus status, RiskLevel riskLevel, String assignedTeam,
        Instant createdAt, Instant updatedAt) {
}
