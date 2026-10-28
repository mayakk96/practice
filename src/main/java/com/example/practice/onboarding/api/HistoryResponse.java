package com.example.practice.onboarding.api;

import com.example.practice.onboarding.model.CaseStatus;
import java.time.Instant;
import java.util.UUID;

public record HistoryResponse(UUID id, CaseStatus previousStatus, CaseStatus newStatus,
        String reason, Instant changedAt) {
}
