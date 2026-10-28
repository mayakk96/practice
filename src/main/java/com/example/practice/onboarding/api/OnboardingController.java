package com.example.practice.onboarding.api;

import com.example.practice.onboarding.service.OnboardingService;
import jakarta.validation.Valid;
import java.net.URI;
import java.util.List;
import java.util.UUID;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/onboarding/cases")
public class OnboardingController {
    private final OnboardingService service;

    public OnboardingController(OnboardingService service) { this.service = service; }

    @PostMapping
    public ResponseEntity<CaseResponse> create(@Valid @RequestBody CreateCaseRequest request,
            @RequestHeader(name = "Idempotency-Key", required = false) String idempotencyKey) {
        CaseCreationResult result = service.createCase(request, idempotencyKey);
        if (result.replayed()) {
            return ResponseEntity.ok().header("Idempotency-Replayed", "true").body(result.caseResponse());
        }
        return ResponseEntity.created(URI.create("/api/onboarding/cases/" + result.caseResponse().id()))
                .body(result.caseResponse());
    }

    @GetMapping
    public PageResponse<CaseResponse> list(@RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {
        return service.listCases(page, size);
    }

    @GetMapping("/{id}")
    public CaseResponse get(@PathVariable UUID id) { return service.getCase(id); }

    @PatchMapping("/{id}/status")
    public CaseResponse changeStatus(@PathVariable UUID id, @Valid @RequestBody ChangeStatusRequest request) {
        return service.changeStatus(id, request);
    }

    @PostMapping("/{id}/documents")
    public ResponseEntity<DocumentResponse> submitDocument(@PathVariable UUID id,
            @Valid @RequestBody SubmitDocumentRequest request) {
        DocumentResponse response = service.submitDocument(id, request);
        return ResponseEntity.created(URI.create("/api/onboarding/cases/" + id + "/documents/" + response.id()))
                .body(response);
    }

    @GetMapping("/{id}/history")
    public List<HistoryResponse> history(@PathVariable UUID id) { return service.history(id); }
}
