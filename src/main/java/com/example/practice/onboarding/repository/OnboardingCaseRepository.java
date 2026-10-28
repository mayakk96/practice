package com.example.practice.onboarding.repository;

import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.model.OnboardingCase;
import jakarta.persistence.LockModeType;
import java.util.Collection;
import java.util.Optional;
import java.util.UUID;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.Pageable;
import org.springframework.data.jpa.repository.EntityGraph;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Lock;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface OnboardingCaseRepository extends JpaRepository<OnboardingCase, UUID> {
    long countByStatus(CaseStatus status);

    @Override
    @EntityGraph(attributePaths = "applicant")
    Page<OnboardingCase> findAll(Pageable pageable);

    @EntityGraph(attributePaths = "applicant")
    Page<OnboardingCase> findByStatusIn(Collection<CaseStatus> statuses, Pageable pageable);

    @Lock(LockModeType.PESSIMISTIC_WRITE)
    @Query("select c from OnboardingCase c where c.id = :id")
    Optional<OnboardingCase> findLockedById(@Param("id") UUID id);
}
