package com.example.practice.onboarding.service;

import com.example.practice.events.DomainEventRecorder;
import com.example.practice.onboarding.api.CaseCreationResult;
import com.example.practice.onboarding.api.CaseResponse;
import com.example.practice.onboarding.api.ChangeStatusRequest;
import com.example.practice.onboarding.api.CreateCaseRequest;
import com.example.practice.onboarding.api.DocumentResponse;
import com.example.practice.onboarding.api.HistoryResponse;
import com.example.practice.onboarding.api.PageResponse;
import com.example.practice.onboarding.api.SubmitDocumentRequest;
import com.example.practice.onboarding.model.Applicant;
import com.example.practice.onboarding.model.CaseDocument;
import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.model.DocumentType;
import com.example.practice.onboarding.model.IdempotencyRequest;
import com.example.practice.onboarding.model.OnboardingCase;
import com.example.practice.onboarding.model.StatusHistory;
import com.example.practice.onboarding.repository.ApplicantRepository;
import com.example.practice.onboarding.repository.CaseDocumentRepository;
import com.example.practice.onboarding.repository.IdempotencyRequestRepository;
import com.example.practice.onboarding.repository.OnboardingCaseRepository;
import com.example.practice.onboarding.repository.StatusHistoryRepository;
import com.example.practice.screening.RiskLevel;
import com.example.practice.screening.RiskScreeningClient;
import com.example.practice.screening.ScreeningUnavailableException;
import jakarta.validation.Valid;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.time.Instant;
import java.util.HexFormat;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.validation.annotation.Validated;

@Service
@Validated
public class OnboardingService {
    private static final Logger log = LoggerFactory.getLogger(OnboardingService.class);
    private static final Set<DocumentType> REQUIRED_DOCUMENTS = Set.of(
            DocumentType.IDENTITY_PROOF, DocumentType.ADDRESS_PROOF);
    private static final Set<CaseStatus> PENDING_STATUSES = Set.of(CaseStatus.CREATED,
            CaseStatus.DOCUMENTS_PENDING, CaseStatus.UNDER_REVIEW, CaseStatus.RISK_REVIEW, CaseStatus.APPROVED);

    private final ApplicantRepository applicants;
    private final OnboardingCaseRepository cases;
    private final CaseDocumentRepository documents;
    private final StatusHistoryRepository histories;
    private final IdempotencyRequestRepository requests;
    private final TransitionPolicy policy;
    private final RiskScreeningClient screening;
    private final DomainEventRecorder events;
    private final TransactionTemplate transactions;

    public OnboardingService(ApplicantRepository applicants, OnboardingCaseRepository cases,
            CaseDocumentRepository documents, StatusHistoryRepository histories,
            IdempotencyRequestRepository requests, TransitionPolicy policy,
            RiskScreeningClient screening, DomainEventRecorder events,
            PlatformTransactionManager transactionManager) {
        this.applicants = applicants;
        this.cases = cases;
        this.documents = documents;
        this.histories = histories;
        this.requests = requests;
        this.policy = policy;
        this.screening = screening;
        this.events = events;
        this.transactions = new TransactionTemplate(transactionManager);
        this.transactions.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    /**
     * The unique idempotency claim is flushed before creating an applicant. Concurrent
     * losers roll back their entire transaction and read the committed winner in a new
     * transaction. Catching the unique violation inside its transaction would be unsafe
     * on PostgreSQL, because that transaction would already be aborted.
     */
    public CaseCreationResult createCase(@Valid CreateCaseRequest request, String idempotencyKey) {
        validateKey(idempotencyKey);
        CreateCaseRequest normalized = normalize(request);
        String fingerprint = fingerprint(normalized);
        try {
            return transactions.execute(status -> createInTransaction(normalized, idempotencyKey, fingerprint));
        } catch (DataIntegrityViolationException conflict) {
            if (idempotencyKey == null) {
                throw conflict;
            }
            CaseCreationResult winner = transactions.execute(status -> requests.findById(idempotencyKey)
                    .map(existing -> replay(existing, fingerprint)).orElse(null));
            if (winner == null) {
                throw conflict;
            }
            return winner;
        }
    }

    private CaseCreationResult createInTransaction(CreateCaseRequest request, String key, String fingerprint) {
        IdempotencyRequest claim = null;
        if (key != null) {
            var existing = requests.findById(key);
            if (existing.isPresent()) {
                return replay(existing.get(), fingerprint);
            }
            claim = requests.saveAndFlush(new IdempotencyRequest(key, fingerprint, Instant.now()));
        }
        Instant now = Instant.now();
        Applicant applicant = applicants.save(new Applicant(
                request.firstName(), request.lastName(), request.email(), now));
        OnboardingCase entity = cases.save(new OnboardingCase(applicant, request.assignedTeam(), now));
        histories.save(new StatusHistory(entity, null, CaseStatus.CREATED, "Case created", now));
        if (claim != null) {
            claim.complete(entity.getId());
        }
        events.record("OnboardingCaseCreated", entity.getId(), Map.of(
                "status", entity.getStatus().name(), "applicantId", applicant.getId().toString()));
        log.info("onboarding_case_created caseId={} status={}", entity.getId(), entity.getStatus());
        return new CaseCreationResult(OnboardingMapper.toResponse(entity), false);
    }

    private CaseCreationResult replay(IdempotencyRequest existing, String fingerprint) {
        if (!existing.getFingerprint().equals(fingerprint)) {
            throw new BusinessConflictException("Idempotency-Key was already used with a different request.");
        }
        if (existing.getCaseId() == null) {
            // Completed transactions always have a case ID; this guards corrupted/manual data.
            throw new BusinessConflictException("The original request is not complete. Retry later.");
        }
        return new CaseCreationResult(OnboardingMapper.toResponse(findCase(existing.getCaseId())), true);
    }

    @Transactional(readOnly = true)
    public CaseResponse getCase(UUID id) {
        return OnboardingMapper.toResponse(findCase(id));
    }

    @Transactional(readOnly = true)
    public PageResponse<CaseResponse> listCases(int page, int size) {
        return mapPage(cases.findAll(pageRequest(page, size)));
    }

    @Transactional(readOnly = true)
    public PageResponse<CaseResponse> listPendingCases(int page, int size) {
        return mapPage(cases.findByStatusIn(PENDING_STATUSES, pageRequest(page, size)));
    }

    @Transactional
    public CaseResponse changeStatus(UUID id, @Valid ChangeStatusRequest request) {
        OnboardingCase entity = findLockedCase(id);
        CaseStatus previous = entity.getStatus();
        policy.validate(previous, request.status());
        RiskLevel risk = entity.getRiskLevel();
        if (request.status() == CaseStatus.APPROVED) {
            if (!documents.findDocumentTypesByCaseId(id).containsAll(REQUIRED_DOCUMENTS)) {
                throw new BusinessConflictException("Approval requires IDENTITY_PROOF and ADDRESS_PROOF documents.");
            }
            var result = screening.screen(id);
            if (result == null || result.riskLevel() == null || result.riskLevel() == RiskLevel.NOT_SCREENED) {
                throw new ScreeningUnavailableException("Screening did not provide a usable risk decision.");
            }
            risk = result.riskLevel();
            if (risk == RiskLevel.HIGH) {
                throw new BusinessConflictException("High-risk cases cannot be approved by this workflow.");
            }
        }
        Instant now = Instant.now();
        entity.transitionTo(request.status(), risk, now);
        cases.save(entity);
        histories.save(new StatusHistory(entity, previous, request.status(), request.reason().strip(), now));
        events.record("OnboardingStatusChanged", id, Map.of(
                "previousStatus", previous.name(), "newStatus", entity.getStatus().name(), "riskLevel", risk.name()));
        if (request.status() == CaseStatus.COMPLETED) {
            events.record("OnboardingCompleted", id, Map.of("status", CaseStatus.COMPLETED.name()));
        }
        log.info("onboarding_status_changed caseId={} previousStatus={} newStatus={}", id, previous, entity.getStatus());
        return OnboardingMapper.toResponse(entity);
    }

    @Transactional
    public DocumentResponse submitDocument(UUID id, @Valid SubmitDocumentRequest request) {
        OnboardingCase entity = findLockedCase(id);
        if (entity.getStatus() != CaseStatus.CREATED && entity.getStatus() != CaseStatus.DOCUMENTS_PENDING) {
            throw new BusinessConflictException("Documents may only be submitted before review starts.");
        }
        if (documents.existsByOnboardingCaseIdAndDocumentType(id, request.documentType())) {
            throw new BusinessConflictException("This document type has already been submitted for the case.");
        }
        Instant now = Instant.now();
        CaseDocument document = documents.save(new CaseDocument(
                entity, request.documentType(), request.reference().strip(), now));
        entity.touch(now);
        cases.save(entity);
        events.record("DocumentSubmitted", id, Map.of(
                "documentId", document.getId().toString(), "documentType", document.getDocumentType().name()));
        log.info("onboarding_document_submitted caseId={} documentId={} documentType={}",
                id, document.getId(), document.getDocumentType());
        return OnboardingMapper.toResponse(document);
    }

    @Transactional(readOnly = true)
    public List<HistoryResponse> history(UUID id) {
        if (!cases.existsById(id)) {
            throw notFound(id);
        }
        return histories.findByOnboardingCaseIdOrderByChangedAtAscIdAsc(id).stream()
                .map(OnboardingMapper::toResponse).toList();
    }

    private OnboardingCase findCase(UUID id) {
        return cases.findById(id).orElseThrow(() -> notFound(id));
    }

    private OnboardingCase findLockedCase(UUID id) {
        return cases.findLockedById(id).orElseThrow(() -> notFound(id));
    }

    private ResourceNotFoundException notFound(UUID id) {
        return new ResourceNotFoundException("Onboarding case " + id + " was not found.");
    }

    private PageRequest pageRequest(int page, int size) {
        if (page < 0 || size < 1 || size > 100) {
            throw new InvalidRequestException("page must be non-negative and size must be between 1 and 100.");
        }
        return PageRequest.of(page, size, Sort.by("createdAt").ascending().and(Sort.by("id")));
    }

    private PageResponse<CaseResponse> mapPage(Page<OnboardingCase> result) {
        return new PageResponse<>(result.getContent().stream().map(OnboardingMapper::toResponse).toList(),
                result.getNumber(), result.getSize(), result.getTotalElements(), result.getTotalPages());
    }

    private void validateKey(String key) {
        if (key != null && !key.matches("[A-Za-z0-9._:-]{1,100}")) {
            throw new InvalidRequestException("Idempotency-Key must contain 1 to 100 letters, digits, '.', '_', ':' or '-'.");
        }
    }

    private CreateCaseRequest normalize(CreateCaseRequest request) {
        return new CreateCaseRequest(request.firstName().strip(), request.lastName().strip(),
                request.email().strip().toLowerCase(Locale.ROOT),
                request.assignedTeam() == null ? "ONBOARDING" : request.assignedTeam());
    }

    private String fingerprint(CreateCaseRequest request) {
        String canonical = frame(request.firstName()) + frame(request.lastName())
                + frame(request.email()) + frame(request.assignedTeam());
        try {
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
                    .digest(canonical.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }

    private String frame(String value) { return value.length() + ":" + value; }
}
