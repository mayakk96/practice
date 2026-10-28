package com.example.practice.onboarding.service;

import com.example.practice.onboarding.api.CaseResponse;
import com.example.practice.onboarding.api.DocumentResponse;
import com.example.practice.onboarding.api.HistoryResponse;
import com.example.practice.onboarding.model.CaseDocument;
import com.example.practice.onboarding.model.OnboardingCase;
import com.example.practice.onboarding.model.StatusHistory;

public final class OnboardingMapper {
    private OnboardingMapper() { }

    public static CaseResponse toResponse(OnboardingCase entity) {
        var applicant = entity.getApplicant();
        return new CaseResponse(entity.getId(), applicant.getId(), applicant.getFirstName(),
                applicant.getLastName(), applicant.getEmail(), entity.getStatus(), entity.getRiskLevel(),
                entity.getAssignedTeam(), entity.getCreatedAt(), entity.getUpdatedAt());
    }

    public static DocumentResponse toResponse(CaseDocument document) {
        return new DocumentResponse(document.getId(), document.getDocumentType(), document.getReference(),
                document.getStatus(), document.getSubmittedAt());
    }

    public static HistoryResponse toResponse(StatusHistory history) {
        return new HistoryResponse(history.getId(), history.getPreviousStatus(), history.getNewStatus(),
                history.getReason(), history.getChangedAt());
    }
}
