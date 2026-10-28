package com.example.practice.onboarding.api;

import com.example.practice.onboarding.model.DocumentType;
import java.time.Instant;
import java.util.UUID;

public record DocumentResponse(UUID id, DocumentType documentType, String reference,
        String status, Instant submittedAt) {
}
