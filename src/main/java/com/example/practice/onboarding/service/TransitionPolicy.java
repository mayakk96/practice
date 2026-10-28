package com.example.practice.onboarding.service;

import com.example.practice.onboarding.model.CaseStatus;
import java.util.Map;
import java.util.Set;
import org.springframework.stereotype.Component;

@Component
public class TransitionPolicy {
    private static final Map<CaseStatus, Set<CaseStatus>> ALLOWED = Map.of(
            CaseStatus.CREATED, Set.of(CaseStatus.DOCUMENTS_PENDING),
            CaseStatus.DOCUMENTS_PENDING, Set.of(CaseStatus.UNDER_REVIEW),
            CaseStatus.UNDER_REVIEW, Set.of(CaseStatus.DOCUMENTS_PENDING, CaseStatus.RISK_REVIEW,
                    CaseStatus.APPROVED, CaseStatus.REJECTED),
            CaseStatus.RISK_REVIEW, Set.of(CaseStatus.DOCUMENTS_PENDING, CaseStatus.APPROVED, CaseStatus.REJECTED),
            CaseStatus.APPROVED, Set.of(CaseStatus.COMPLETED),
            CaseStatus.REJECTED, Set.of(),
            CaseStatus.COMPLETED, Set.of());

    public boolean canTransition(CaseStatus current, CaseStatus target) {
        return current != null && target != null && allowedTransitions(current).contains(target);
    }

    public Set<CaseStatus> allowedTransitions(CaseStatus current) {
        return current == null ? Set.of() : ALLOWED.getOrDefault(current, Set.of());
    }

    public void validate(CaseStatus current, CaseStatus target) {
        if (!canTransition(current, target)) {
            throw new BusinessConflictException("Cannot transition from " + current + " to " + target + ".");
        }
    }
}
