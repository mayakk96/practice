package com.example.practice.onboarding;

import com.example.practice.events.DomainEventRecorder;
import com.example.practice.onboarding.api.ChangeStatusRequest;
import com.example.practice.onboarding.api.CreateCaseRequest;
import com.example.practice.onboarding.api.SubmitDocumentRequest;
import com.example.practice.onboarding.model.Applicant;
import com.example.practice.onboarding.model.CaseDocument;
import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.model.DocumentType;
import com.example.practice.onboarding.model.OnboardingCase;
import com.example.practice.onboarding.model.StatusHistory;
import com.example.practice.onboarding.repository.ApplicantRepository;
import com.example.practice.onboarding.repository.CaseDocumentRepository;
import com.example.practice.onboarding.repository.IdempotencyRequestRepository;
import com.example.practice.onboarding.repository.OnboardingCaseRepository;
import com.example.practice.onboarding.repository.StatusHistoryRepository;
import com.example.practice.onboarding.service.BusinessConflictException;
import com.example.practice.onboarding.service.InvalidRequestException;
import com.example.practice.onboarding.service.OnboardingService;
import com.example.practice.onboarding.service.ResourceNotFoundException;
import com.example.practice.onboarding.service.TransitionPolicy;
import com.example.practice.screening.RiskLevel;
import com.example.practice.screening.RiskScreeningClient;
import com.example.practice.screening.ScreeningResult;
import com.example.practice.screening.ScreeningUnavailableException;
import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.SimpleTransactionStatus;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyMap;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

/** Pure business tests: no Spring context, HTTP server, database or Kafka broker. */
@ExtendWith(MockitoExtension.class)
class OnboardingServiceTest {

    @Mock private ApplicantRepository applicants;
    @Mock private OnboardingCaseRepository cases;
    @Mock private CaseDocumentRepository documents;
    @Mock private StatusHistoryRepository histories;
    @Mock private IdempotencyRequestRepository idempotency;
    @Mock private RiskScreeningClient screening;
    @Mock private DomainEventRecorder events;
    @Mock private PlatformTransactionManager transactions;

    private OnboardingService service;

    @BeforeEach
    void setUp() {
        service = new OnboardingService(applicants, cases, documents, histories, idempotency,
                new TransitionPolicy(), screening, events, transactions);
    }

    @Test
    void creationNormalizesInputAndRecordsInitialHistoryAndDomainEvent() {
        when(transactions.getTransaction(any())).thenReturn(new SimpleTransactionStatus());
        when(applicants.save(any(Applicant.class))).thenAnswer(invocation -> invocation.getArgument(0));
        when(cases.save(any(OnboardingCase.class))).thenAnswer(invocation -> invocation.getArgument(0));

        var result = service.createCase(new CreateCaseRequest(" Demo ", " Applicant ", "DEMO@EXAMPLE.COM", null), null);

        assertThat(result.replayed()).isFalse();
        assertThat(result.caseResponse().firstName()).isEqualTo("Demo");
        assertThat(result.caseResponse().lastName()).isEqualTo("Applicant");
        assertThat(result.caseResponse().email()).isEqualTo("demo@example.com");
        assertThat(result.caseResponse().assignedTeam()).isEqualTo("ONBOARDING");
        assertThat(result.caseResponse().status()).isEqualTo(CaseStatus.CREATED);
        var history = ArgumentCaptor.forClass(StatusHistory.class);
        verify(histories).save(history.capture());
        assertThat(history.getValue().getPreviousStatus()).isNull();
        assertThat(history.getValue().getNewStatus()).isEqualTo(CaseStatus.CREATED);
        verify(events).record(eq("OnboardingCaseCreated"), eq(result.caseResponse().id()), anyMap());
        verify(transactions).commit(any());
        verifyNoInteractions(screening);
    }

    @Test
    void getMapsTheEntityToAResponseWithoutLeakingTheEntity() {
        OnboardingCase entity = caseAt(CaseStatus.CREATED);
        when(cases.findById(entity.getId())).thenReturn(Optional.of(entity));

        var response = service.getCase(entity.getId());

        assertThat(response.id()).isEqualTo(entity.getId());
        assertThat(response.applicantId()).isEqualTo(entity.getApplicant().getId());
        assertThat(response.status()).isEqualTo(CaseStatus.CREATED);
        verifyNoInteractions(screening, events);
    }

    @Test
    void getMissingCaseThrowsADomainNotFoundException() {
        UUID id = UUID.randomUUID();
        when(cases.findById(id)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> service.getCase(id)).isInstanceOf(ResourceNotFoundException.class);
    }

    @Test
    void statusShortcutIsRejectedBeforeSideEffects() {
        OnboardingCase entity = caseAt(CaseStatus.CREATED);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> service.changeStatus(entity.getId(),
                new ChangeStatusRequest(CaseStatus.COMPLETED, "Attempted shortcut")))
                .isInstanceOf(BusinessConflictException.class);

        assertThat(entity.getStatus()).isEqualTo(CaseStatus.CREATED);
        verify(cases, never()).save(any());
        verifyNoInteractions(histories, documents, screening, events);
    }

    @Test
    void approvalRequiresAllRequiredDocumentsBeforeCallingTheProvider() {
        OnboardingCase entity = caseAt(CaseStatus.UNDER_REVIEW);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));
        when(documents.findDocumentTypesByCaseId(entity.getId())).thenReturn(Set.of(DocumentType.IDENTITY_PROOF));

        assertThatThrownBy(() -> service.changeStatus(entity.getId(),
                new ChangeStatusRequest(CaseStatus.APPROVED, "Request approval")))
                .isInstanceOf(BusinessConflictException.class);

        assertThat(entity.getStatus()).isEqualTo(CaseStatus.UNDER_REVIEW);
        verifyNoInteractions(screening, histories, events);
    }

    @Test
    void successfulApprovalUsesTheRiskDecisionAndRecordsTransitionHistory() {
        OnboardingCase entity = approvalReadyCase();
        when(screening.screen(entity.getId())).thenReturn(new ScreeningResult(RiskLevel.LOW, "DEMO-LOW"));

        var response = service.changeStatus(entity.getId(),
                new ChangeStatusRequest(CaseStatus.APPROVED, " All required checks passed "));

        assertThat(response.status()).isEqualTo(CaseStatus.APPROVED);
        assertThat(response.riskLevel()).isEqualTo(RiskLevel.LOW);
        var history = ArgumentCaptor.forClass(StatusHistory.class);
        verify(histories).save(history.capture());
        assertThat(history.getValue().getPreviousStatus()).isEqualTo(CaseStatus.UNDER_REVIEW);
        assertThat(history.getValue().getNewStatus()).isEqualTo(CaseStatus.APPROVED);
        assertThat(history.getValue().getReason()).isEqualTo("All required checks passed");
        verify(events).record(eq("OnboardingStatusChanged"), eq(entity.getId()), anyMap());
    }

    @Test
    void highRiskApprovalIsRejectedWithoutChangingState() {
        OnboardingCase entity = approvalReadyCase();
        when(screening.screen(entity.getId())).thenReturn(new ScreeningResult(RiskLevel.HIGH, "DEMO-HIGH"));

        assertThatThrownBy(() -> service.changeStatus(entity.getId(),
                new ChangeStatusRequest(CaseStatus.APPROVED, "Request approval")))
                .isInstanceOf(BusinessConflictException.class);

        assertThat(entity.getStatus()).isEqualTo(CaseStatus.UNDER_REVIEW);
        verify(cases, never()).save(any());
        verifyNoInteractions(histories, events);
    }

    @Test
    void providerFailureIsPropagatedBeforeAnyStatusMutation() {
        OnboardingCase entity = approvalReadyCase();
        when(screening.screen(entity.getId())).thenThrow(new ScreeningUnavailableException("Provider unavailable"));

        assertThatThrownBy(() -> service.changeStatus(entity.getId(),
                new ChangeStatusRequest(CaseStatus.APPROVED, "Request approval")))
                .isInstanceOf(ScreeningUnavailableException.class);

        assertThat(entity.getStatus()).isEqualTo(CaseStatus.UNDER_REVIEW);
        verifyNoInteractions(histories, events);
    }

    @Test
    void completingAnApprovedCaseRecordsBothStatusChangeAndCompletionEvents() {
        OnboardingCase entity = caseAt(CaseStatus.APPROVED);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));

        service.changeStatus(entity.getId(), new ChangeStatusRequest(CaseStatus.COMPLETED, "Workflow finished"));

        assertThat(entity.getStatus()).isEqualTo(CaseStatus.COMPLETED);
        verify(events).record(eq("OnboardingStatusChanged"), eq(entity.getId()), anyMap());
        verify(events).record("OnboardingCompleted", entity.getId(), Map.of("status", "COMPLETED"));
        verifyNoInteractions(screening);
    }

    @Test
    void documentSubmissionStoresMetadataAndEmitsAnEvent() {
        OnboardingCase entity = caseAt(CaseStatus.DOCUMENTS_PENDING);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));
        when(documents.save(any(CaseDocument.class))).thenAnswer(invocation -> invocation.getArgument(0));

        var result = service.submitDocument(entity.getId(),
                new SubmitDocumentRequest(DocumentType.IDENTITY_PROOF, " DEMO-001 "));

        assertThat(result.documentType()).isEqualTo(DocumentType.IDENTITY_PROOF);
        assertThat(result.reference()).isEqualTo("DEMO-001");
        verify(events).record(eq("DocumentSubmitted"), eq(entity.getId()), anyMap());
        verifyNoInteractions(screening);
    }

    @Test
    void duplicateDocumentIsRejectedWithoutAnotherInsertOrEvent() {
        OnboardingCase entity = caseAt(CaseStatus.DOCUMENTS_PENDING);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));
        when(documents.existsByOnboardingCaseIdAndDocumentType(entity.getId(), DocumentType.IDENTITY_PROOF))
                .thenReturn(true);

        assertThatThrownBy(() -> service.submitDocument(entity.getId(),
                new SubmitDocumentRequest(DocumentType.IDENTITY_PROOF, "DEMO-001")))
                .isInstanceOf(BusinessConflictException.class);

        verify(documents, never()).save(any());
        verifyNoInteractions(events);
    }

    @Test
    void documentsCannotChangeAfterReviewStarts() {
        OnboardingCase entity = caseAt(CaseStatus.UNDER_REVIEW);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));

        assertThatThrownBy(() -> service.submitDocument(entity.getId(),
                new SubmitDocumentRequest(DocumentType.IDENTITY_PROOF, "DEMO-001")))
                .isInstanceOf(BusinessConflictException.class);
        verifyNoInteractions(documents, events);
    }

    @Test
    void invalidPageBoundsAreRejectedBeforeQueryingTheDatabase() {
        assertThatThrownBy(() -> service.listCases(-1, 20)).isInstanceOf(InvalidRequestException.class);
        assertThatThrownBy(() -> service.listCases(0, 0)).isInstanceOf(InvalidRequestException.class);
        assertThatThrownBy(() -> service.listCases(0, 101)).isInstanceOf(InvalidRequestException.class);
        verifyNoInteractions(cases);
    }

    private OnboardingCase approvalReadyCase() {
        OnboardingCase entity = caseAt(CaseStatus.UNDER_REVIEW);
        when(cases.findLockedById(entity.getId())).thenReturn(Optional.of(entity));
        when(documents.findDocumentTypesByCaseId(entity.getId()))
                .thenReturn(Set.of(DocumentType.IDENTITY_PROOF, DocumentType.ADDRESS_PROOF));
        return entity;
    }

    private OnboardingCase caseAt(CaseStatus status) {
        Instant now = Instant.parse("2026-01-01T00:00:00Z");
        Applicant applicant = new Applicant("Demo", "Applicant", "demo@example.com", now);
        OnboardingCase entity = new OnboardingCase(applicant, "ONBOARDING", now);
        entity.transitionTo(status, status == CaseStatus.APPROVED ? RiskLevel.LOW : RiskLevel.NOT_SCREENED, now);
        return entity;
    }
}
