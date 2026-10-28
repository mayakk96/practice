package com.example.practice.onboarding.repository;

import com.example.practice.onboarding.model.StatusHistory;
import java.util.List;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;

public interface StatusHistoryRepository extends JpaRepository<StatusHistory, UUID> {
    List<StatusHistory> findByOnboardingCaseIdOrderByChangedAtAscIdAsc(UUID caseId);
}
