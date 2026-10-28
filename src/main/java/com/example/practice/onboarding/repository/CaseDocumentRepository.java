package com.example.practice.onboarding.repository;

import com.example.practice.onboarding.model.CaseDocument;
import com.example.practice.onboarding.model.DocumentType;
import java.util.Set;
import java.util.UUID;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

public interface CaseDocumentRepository extends JpaRepository<CaseDocument, UUID> {
    boolean existsByOnboardingCaseIdAndDocumentType(UUID caseId, DocumentType documentType);

    @Query("select d.documentType from CaseDocument d where d.onboardingCase.id = :caseId")
    Set<DocumentType> findDocumentTypesByCaseId(@Param("caseId") UUID caseId);
}
