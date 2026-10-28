package com.example.practice.mcp;

import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.example.practice.knowledge.KnowledgeService;
import com.example.practice.onboarding.api.CaseResponse;
import com.example.practice.onboarding.api.HistoryResponse;
import com.example.practice.onboarding.api.PageResponse;
import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.service.OnboardingService;
import com.example.practice.onboarding.service.ResourceNotFoundException;
import com.example.practice.screening.RiskLevel;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class OnboardingToolsTest {
    private final OnboardingService onboarding = mock(OnboardingService.class);
    private final KnowledgeService knowledge = mock(KnowledgeService.class);
    private final ObjectMapper mapper = JsonMapper.builder().addModule(new JavaTimeModule()).build();
    private final OnboardingTools tools = new OnboardingTools(onboarding, knowledge, mapper);

    @Test
    void returnsSanitizedCaseMetadataWithoutApplicantInformation() throws Exception {
        UUID id = UUID.randomUUID();
        when(onboarding.getCase(id)).thenReturn(caseResponse(id));

        var result = tools.getCase(id.toString());

        assertThat(result.isError()).isFalse();
        String output = mapper.writeValueAsString(result.structuredContent());
        assertThat(output).contains(id.toString(), "CREATED").doesNotContain("firstName", "lastName", "email", "fictional@example.com", "Demo");
    }

    @Test
    void excludesFreeTextHistoryReasons() throws Exception {
        UUID id = UUID.randomUUID();
        when(onboarding.history(id)).thenReturn(List.of(new HistoryResponse(UUID.randomUUID(), CaseStatus.CREATED,
                CaseStatus.DOCUMENTS_PENDING, "sensitive-free-text-do-not-expose", Instant.now())));

        String output = mapper.writeValueAsString(tools.history(id.toString()).structuredContent());

        assertThat(output).contains("DOCUMENTS_PENDING").doesNotContain("reason", "sensitive-free-text-do-not-expose");
    }

    @Test
    void boundedPendingListDelegatesToTheApplicationServiceQuery() throws Exception {
        UUID id = UUID.randomUUID();
        when(onboarding.listPendingCases(0, 20)).thenReturn(new PageResponse<>(List.of(caseResponse(id)), 0, 20, 1, 1));

        var result = tools.listPendingCases(null, null);

        assertThat(result.isError()).isFalse();
        assertThat(mapper.writeValueAsString(result.structuredContent())).contains(id.toString()).doesNotContain("email");
    }

    @Test
    void invalidArgumentsAreRejectedBeforeDatabaseAccess() {
        assertThat(tools.getCase("not-a-uuid").isError()).isTrue();
        assertThat(tools.listPendingCases(0, 51).isError()).isTrue();
        assertThat(tools.listPendingCases(-1, 20).isError()).isTrue();
        verifyNoInteractions(onboarding);
    }

    @Test
    void errorsHaveStableCodesWithoutLeakingUnderlyingExceptionMessages() {
        UUID id = UUID.randomUUID();
        when(onboarding.getCase(id)).thenThrow(new ResourceNotFoundException("sensitive-data"));
        var result = tools.getCase(id.toString());
        assertThat(result.isError()).isTrue();
        assertThat(((Map<?, ?>) result.structuredContent()).get("code")).isEqualTo("NOT_FOUND");
        assertThat(result.content().toString()).doesNotContain("sensitive-data");
    }

    private CaseResponse caseResponse(UUID id) {
        return new CaseResponse(id, UUID.randomUUID(), "Demo", "Applicant", "fictional@example.com", CaseStatus.CREATED,
                RiskLevel.NOT_SCREENED, "ONBOARDING", Instant.now(), Instant.now());
    }
}
