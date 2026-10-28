package com.example.practice.mcp;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Supplier;

import com.example.practice.knowledge.KnowledgeRequest;
import com.example.practice.knowledge.KnowledgeService;
import com.example.practice.knowledge.KnowledgeUnavailableException;
import com.example.practice.onboarding.api.CaseResponse;
import com.example.practice.onboarding.api.HistoryResponse;
import com.example.practice.onboarding.api.PageResponse;
import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.service.OnboardingService;
import com.example.practice.onboarding.service.ResourceNotFoundException;
import com.example.practice.screening.RiskLevel;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.modelcontextprotocol.spec.McpSchema.CallToolResult;
import jakarta.validation.ConstraintViolationException;
import org.springaicommunity.mcp.annotation.McpTool;
import org.springaicommunity.mcp.annotation.McpToolParam;
import org.springframework.stereotype.Component;

/** Read-only adapters: the application service remains the single source of workflow behavior. */
@Component
public class OnboardingTools {
    private final OnboardingService onboarding;
    private final KnowledgeService knowledge;
    private final ObjectMapper objectMapper;

    public OnboardingTools(OnboardingService onboarding, KnowledgeService knowledge, ObjectMapper objectMapper) {
        this.onboarding = onboarding;
        this.knowledge = knowledge;
        this.objectMapper = objectMapper;
    }

    @McpTool(name = "get_onboarding_case", description = "Read a fictional case's status by UUID. Returns identifiers and workflow metadata only; no applicant information.",
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false))
    public CallToolResult getCase(@McpToolParam(description = "Onboarding case UUID", required = true) String caseId) {
        return execute(() -> CaseSummary.from(onboarding.getCase(parseCaseId(caseId))));
    }

    @McpTool(name = "list_pending_cases", description = "Read a bounded page of non-terminal fictional cases. No applicant information is included.",
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false))
    public CallToolResult listPendingCases(
            @McpToolParam(description = "Zero-based page, 0 through 10000; defaults to 0", required = false) Integer page,
            @McpToolParam(description = "Page size, 1 through 50; defaults to 20", required = false) Integer size) {
        return execute(() -> {
            int requestedPage = page == null ? 0 : page;
            int requestedSize = size == null ? 20 : size;
            if (requestedPage < 0 || requestedPage > 10000 || requestedSize < 1 || requestedSize > 50) {
                throw new IllegalArgumentException("Page must be 0..10000 and size must be 1..50.");
            }
            PageResponse<CaseResponse> result = onboarding.listPendingCases(requestedPage, requestedSize);
            return new PageResponse<>(result.items().stream().map(CaseSummary::from).toList(), result.page(),
                    result.size(), result.totalElements(), result.totalPages());
        });
    }

    @McpTool(name = "get_case_status_history", description = "Read status transitions for a fictional case UUID. Free-text reasons and applicant information are omitted.",
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false))
    public CallToolResult history(@McpToolParam(description = "Onboarding case UUID", required = true) String caseId) {
        return execute(() -> {
            List<HistoryResponse> history = onboarding.history(parseCaseId(caseId));
            return Map.of("items", history.stream().limit(100).map(HistorySummary::from).toList(),
                    "truncated", history.size() > 100);
        });
    }

    @McpTool(name = "search_onboarding_policy", description = "Search bundled fictional policies with vector retrieval and return an evidence-based educational answer with citations. Does not make case decisions.",
            annotations = @McpTool.McpAnnotations(readOnlyHint = true, destructiveHint = false, idempotentHint = true, openWorldHint = false))
    public CallToolResult searchPolicy(
            @McpToolParam(description = "Policy question, 1 through 500 characters; use no personal or confidential information", required = true) String query,
            @McpToolParam(description = "Maximum retrieved chunks, 1 through 5; defaults to 3", required = false) Integer topK) {
        return execute(() -> knowledge.search(new KnowledgeRequest(query, topK)));
    }

    private UUID parseCaseId(String value) {
        if (value == null || value.length() != 36) {
            throw new IllegalArgumentException("A canonical case UUID is required.");
        }
        UUID id = UUID.fromString(value);
        if (!id.toString().equalsIgnoreCase(value)) {
            throw new IllegalArgumentException("A canonical case UUID is required.");
        }
        return id;
    }

    private CallToolResult execute(Supplier<?> action) {
        try {
            Map<String, Object> output = objectMapper.convertValue(action.get(), new TypeReference<>() { });
            return CallToolResult.builder().structuredContent(output).addTextContent(objectMapper.writeValueAsString(output)).build();
        } catch (ResourceNotFoundException exception) {
            return failure("NOT_FOUND", "The requested fictional onboarding case was not found.");
        } catch (IllegalArgumentException | ConstraintViolationException exception) {
            return failure("INVALID_INPUT", "Input must match the tool's documented UUID, page, size, or query limits.");
        } catch (KnowledgeUnavailableException exception) {
            return failure("MODEL_UNAVAILABLE", "The configured policy answer model is unavailable.");
        } catch (Exception exception) {
            // Never expose exception text: it can contain SQL, credentials, or user-supplied values.
            return failure("INTERNAL_ERROR", "The tool could not complete the request.");
        }
    }

    private CallToolResult failure(String code, String message) {
        Map<String, Object> error = Map.of("code", code, "message", message);
        return CallToolResult.builder().isError(true).structuredContent(error).addTextContent(message).build();
    }

    public record CaseSummary(UUID id, CaseStatus status, RiskLevel riskLevel, Instant createdAt, Instant updatedAt) {
        static CaseSummary from(CaseResponse source) {
            return new CaseSummary(source.id(), source.status(), source.riskLevel(), source.createdAt(), source.updatedAt());
        }
    }

    public record HistorySummary(UUID id, CaseStatus previousStatus, CaseStatus newStatus, Instant changedAt) {
        static HistorySummary from(HistoryResponse source) {
            return new HistorySummary(source.id(), source.previousStatus(), source.newStatus(), source.changedAt());
        }
    }
}
