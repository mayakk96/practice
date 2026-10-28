package com.example.practice.onboarding;

import com.example.practice.screening.RiskLevel;
import com.example.practice.screening.RiskScreeningClient;
import com.example.practice.screening.ScreeningResult;
import com.example.practice.screening.ScreeningUnavailableException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Stream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Tests the real MVC, service, transaction and database layers together. */
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class OnboardingApiIntegrationTest {

    private static final String CASES = "/api/onboarding/cases";

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper json;

    @Autowired
    private JdbcTemplate jdbc;

    @MockitoBean
    private RiskScreeningClient screening;

    @BeforeEach
    void resetDatabaseAndScreening() {
        // These tests deliberately do not wrap requests in a test transaction:
        // subsequent HTTP requests must observe committed database state.
        jdbc.execute("SET REFERENTIAL_INTEGRITY FALSE");
        try {
            jdbc.queryForList("SELECT table_name FROM information_schema.tables "
                            + "WHERE table_schema = 'public' AND table_type = 'BASE TABLE'", String.class)
                    .stream().filter(name -> !name.equalsIgnoreCase("flyway_schema_history"))
                    .forEach(name -> jdbc.execute("DELETE FROM \"" + name + "\""));
        } finally {
            jdbc.execute("SET REFERENTIAL_INTEGRITY TRUE");
        }
        reset(screening);
        when(screening.screen(any(UUID.class))).thenReturn(new ScreeningResult(RiskLevel.LOW, "DEMO-LOW"));
    }

    @Test
    void emptyDatabaseReturnsAnEmptyPage() throws Exception {
        mvc.perform(get(CASES))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isEmpty())
                .andExpect(jsonPath("$.page").value(0))
                .andExpect(jsonPath("$.totalElements").value(0));
    }

    @Test
    void completeWorkflowPersistsDocumentsStatusHistoryAndEvents() throws Exception {
        JsonNode created = createCase();
        UUID id = UUID.fromString(created.path("id").asText());

        assertThat(created.path("status").asText()).isEqualTo("CREATED");
        assertThat(created.path("assignedTeam").asText()).isEqualTo("ONBOARDING");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM applicant", Long.class)).isEqualTo(1);

        mvc.perform(get(CASES + "/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.applicantId").isNotEmpty())
                .andExpect(jsonPath("$.email").value("demo@example.com"));

        changeStatus(id, "DOCUMENTS_PENDING");
        submitDocument(id, "IDENTITY_PROOF", "DEMO-IDENTITY-001");
        submitDocument(id, "ADDRESS_PROOF", "DEMO-ADDRESS-001");
        changeStatus(id, "UNDER_REVIEW");
        changeStatus(id, "APPROVED");
        changeStatus(id, "COMPLETED");

        mvc.perform(get(CASES + "/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("COMPLETED"))
                .andExpect(jsonPath("$.riskLevel").value("LOW"));
        verify(screening).screen(id);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_document", Long.class)).isEqualTo(2);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM event_outbox", Long.class)).isGreaterThanOrEqualTo(8);
        assertThat(jdbc.queryForList("SELECT event_json FROM event_outbox", String.class))
                .allSatisfy(event -> assertThat(event).doesNotContain("demo@example.com", "DEMO-IDENTITY-001"));

        JsonNode history = body(mvc.perform(get(CASES + "/{id}/history", id))
                .andExpect(status().isOk()).andReturn());
        List<String> statuses = new ArrayList<>();
        history.forEach(entry -> {
            statuses.add(entry.path("newStatus").asText());
            assertThat(entry.path("changedAt").asText()).isNotBlank();
            assertThat(entry.path("reason").asText()).isNotBlank();
        });
        assertThat(statuses).containsSubsequence("DOCUMENTS_PENDING", "UNDER_REVIEW", "APPROVED", "COMPLETED");
    }

    @Test
    void statusCannotSkipTheTransitionPolicy() throws Exception {
        UUID id = UUID.fromString(createCase().path("id").asText());

        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("status", "COMPLETED", "reason", "Attempted shortcut"))))
                .andExpect(status().isConflict())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(409))
                .andExpect(jsonPath("$.detail").isNotEmpty());
        mvc.perform(get(CASES + "/{id}", id)).andExpect(jsonPath("$.status").value("CREATED"));
    }

    @Test
    void approvalRequiresBothDocumentTypes() throws Exception {
        UUID id = prepareUnderReview(false);

        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"APPROVED\",\"reason\":\"Request approval\"}"))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409));
        mvc.perform(get(CASES + "/{id}", id)).andExpect(jsonPath("$.status").value("UNDER_REVIEW"));
    }

    @Test
    void highRiskCannotBeApproved() throws Exception {
        UUID id = prepareUnderReview(true);
        when(screening.screen(id)).thenReturn(new ScreeningResult(RiskLevel.HIGH, "DEMO-HIGH"));

        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"APPROVED\",\"reason\":\"Request approval\"}"))
                .andExpect(status().isConflict());
        mvc.perform(get(CASES + "/{id}", id)).andExpect(jsonPath("$.status").value("UNDER_REVIEW"));
    }

    @Test
    void downstreamFailureRollsBackStatusAndHistory() throws Exception {
        UUID id = prepareUnderReview(true);
        Long historyBefore = jdbc.queryForObject("SELECT count(*) FROM status_history", Long.class);
        Long eventsBefore = jdbc.queryForObject("SELECT count(*) FROM event_outbox", Long.class);
        when(screening.screen(id)).thenThrow(new ScreeningUnavailableException("Fictional provider unavailable"));

        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"APPROVED\",\"reason\":\"Request approval\"}"))
                .andExpect(status().isServiceUnavailable())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(503));

        mvc.perform(get(CASES + "/{id}", id))
                .andExpect(jsonPath("$.status").value("UNDER_REVIEW"));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM status_history", Long.class)).isEqualTo(historyBefore);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM event_outbox", Long.class)).isEqualTo(eventsBefore);
    }

    @Test
    void duplicateDocumentSubmissionReturnsConflictWithoutAnotherRow() throws Exception {
        UUID id = UUID.fromString(createCase().path("id").asText());
        submitDocument(id, "IDENTITY_PROOF", "DEMO-IDENTITY-001");

        mvc.perform(post(CASES + "/{id}/documents", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"documentType\":\"IDENTITY_PROOF\",\"reference\":\"DEMO-IDENTITY-001\"}"))
                .andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_document", Long.class)).isEqualTo(1);
    }

    @Test
    void replayingAnIdempotencyKeyReturnsTheOriginalCase() throws Exception {
        String key = UUID.randomUUID().toString();
        MvcResult first = mvc.perform(post(CASES).header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isCreated()).andReturn();
        MvcResult replay = mvc.perform(post(CASES).header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isOk())
                .andExpect(header().string("Idempotency-Replayed", "true")).andReturn();

        assertThat(body(replay).path("id").asText()).isEqualTo(body(first).path("id").asText());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM applicant", Long.class)).isEqualTo(1);
    }

    @Test
    void reusingAKeyWithDifferentInputReturnsConflict() throws Exception {
        String key = UUID.randomUUID().toString();
        mvc.perform(post(CASES).header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isCreated());
        mvc.perform(post(CASES).header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"firstName\":\"Other\",\"lastName\":\"Applicant\",\"email\":\"other@example.com\"}"))
                .andExpect(status().isConflict());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
    }

    @Test
    void simultaneousIdenticalRequestsCannotCreateDuplicateCases() throws Exception {
        String key = UUID.randomUUID().toString();
        String request = createRequest();
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);
        try (var executor = Executors.newFixedThreadPool(2)) {
            var first = executor.submit(() -> concurrentCreate(key, request, ready, start));
            var second = executor.submit(() -> concurrentCreate(key, request, ready, start));
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            MvcResult firstResult = first.get(20, TimeUnit.SECONDS);
            MvcResult secondResult = second.get(20, TimeUnit.SECONDS);
            assertThat(List.of(firstResult.getResponse().getStatus(), secondResult.getResponse().getStatus()))
                    .containsExactlyInAnyOrder(201, 200);
            assertThat(body(firstResult).path("id").asText()).isEqualTo(body(secondResult).path("id").asText());
            assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
        }
    }

    @ParameterizedTest
    @MethodSource("invalidCreateRequests")
    void invalidCreateRequestsReturnMachineReadableErrors(String request) throws Exception {
        mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(400))
                .andExpect(jsonPath("$.title").isNotEmpty());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isZero();
    }

    static Stream<String> invalidCreateRequests() {
        return Stream.of(
                "{}",
                "{\"firstName\":\" \",\"lastName\":\"Applicant\",\"email\":\"demo@example.com\"}",
                "{\"firstName\":\"Demo\",\"lastName\":\"Applicant\",\"email\":\"invalid-email\"}",
                "{\"firstName\":\"Demo\",\"lastName\":\"Applicant\",\"email\":\"demo@gmail.com\"}",
                "{\"firstName\":\"Demo\",\"lastName\":\"Applicant\",\"email\":\"" + "x".repeat(260) + "@example.com\"}");
    }

    @Test
    void malformedJsonAndUnknownStatusAreBadRequests() throws Exception {
        mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON).content("{"))
                .andExpect(status().isBadRequest()).andExpect(jsonPath("$.status").value(400));
        UUID id = UUID.fromString(createCase().path("id").asText());
        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"status\":\"UNKNOWN\",\"reason\":\"Demo\"}"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void unknownResourcesReturnConsistentNotFoundErrors() throws Exception {
        UUID missing = UUID.randomUUID();
        mvc.perform(get(CASES + "/{id}", missing))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(404));
        mvc.perform(get(CASES + "/{id}/history", missing)).andExpect(status().isNotFound());
        mvc.perform(post(CASES + "/{id}/documents", missing)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"documentType\":\"IDENTITY_PROOF\",\"reference\":\"DEMO-001\"}"))
                .andExpect(status().isNotFound());
    }

    @Test
    void listSupportsBoundedPagination() throws Exception {
        createCase();
        createCase();
        mvc.perform(get(CASES).param("page", "0").param("size", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items.length()").value(1))
                .andExpect(jsonPath("$.totalElements").value(2))
                .andExpect(jsonPath("$.totalPages").value(2));
        mvc.perform(get(CASES).param("size", "101")).andExpect(status().isBadRequest());
        mvc.perform(get(CASES).param("page", "-1")).andExpect(status().isBadRequest());
    }

    @Test
    void emptyOrOversizedReasonsAndInvalidDocumentMetadataAreRejected() throws Exception {
        UUID id = UUID.fromString(createCase().path("id").asText());
        for (String reason : List.of("", "x".repeat(501))) {
            mvc.perform(patch(CASES + "/{id}/status", id)
                            .contentType(MediaType.APPLICATION_JSON)
                            .content(json.writeValueAsString(Map.of("status", "DOCUMENTS_PENDING", "reason", reason))))
                    .andExpect(status().isBadRequest());
        }
        mvc.perform(post(CASES + "/{id}/documents", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"documentType\":\"IDENTITY_PROOF\",\"reference\":\" \"}"))
                .andExpect(status().isBadRequest());
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_document", Long.class)).isZero();
    }

    @Test
    void rejectsOversizedIdempotencyKeys() throws Exception {
        mvc.perform(post(CASES).header("Idempotency-Key", "k".repeat(101))
                        .contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isBadRequest());
    }

    @Test
    void acceptsBoundaryLengthsAndRejectsValuesBeyondThem() throws Exception {
        String longestName = "D".repeat(80);
        var created = mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("firstName", longestName,
                                "lastName", "Applicant", "email", "boundary@example.com"))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.firstName").value(longestName)).andReturn();
        String id = body(created).path("id").asText();
        mvc.perform(patch(CASES + "/{id}/status", id).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("status", "DOCUMENTS_PENDING", "reason", "r".repeat(500)))))
                .andExpect(status().isOk());
        mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("firstName", "D".repeat(81),
                                "lastName", "Applicant", "email", "boundary@example.com"))))
                .andExpect(status().isBadRequest());
    }

    @Test
    void idempotencyUsesNormalizedMeaningRatherThanJsonFormatting() throws Exception {
        String key = UUID.randomUUID().toString();
        var first = mvc.perform(post(CASES).header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isCreated()).andReturn();
        mvc.perform(post(CASES).header("Idempotency-Key", key).contentType(MediaType.APPLICATION_JSON)
                        .content("{\"email\":\"DEMO@EXAMPLE.COM\",\"lastName\":\" Applicant \","
                                + "\"firstName\":\" Demo \",\"assignedTeam\":\"ONBOARDING\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(body(first).path("id").asText()));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case", Long.class)).isEqualTo(1);
    }

    private JsonNode createCase() throws Exception {
        MvcResult result = mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON).content(createRequest()))
                .andExpect(status().isCreated())
                .andExpect(header().exists("Location"))
                .andReturn();
        JsonNode created = body(result);
        assertThat(result.getResponse().getHeader("Location")).endsWith("/" + created.path("id").asText());
        return created;
    }

    private String createRequest() {
        return "{\"firstName\":\"Demo\",\"lastName\":\"Applicant\",\"email\":\"demo@example.com\"}";
    }

    private UUID prepareUnderReview(boolean withAllDocuments) throws Exception {
        UUID id = UUID.fromString(createCase().path("id").asText());
        changeStatus(id, "DOCUMENTS_PENDING");
        submitDocument(id, "IDENTITY_PROOF", "DEMO-IDENTITY-001");
        if (withAllDocuments) {
            submitDocument(id, "ADDRESS_PROOF", "DEMO-ADDRESS-001");
        }
        changeStatus(id, "UNDER_REVIEW");
        return id;
    }

    private void changeStatus(UUID id, String status) throws Exception {
        mvc.perform(patch(CASES + "/{id}/status", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("status", status, "reason", "Fictional demonstration transition"))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value(status));
    }

    private void submitDocument(UUID id, String type, String reference) throws Exception {
        mvc.perform(post(CASES + "/{id}/documents", id)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("documentType", type, "reference", reference))))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.documentType").value(type));
    }

    private MvcResult concurrentCreate(String key, String request, CountDownLatch ready, CountDownLatch start) throws Exception {
        ready.countDown();
        if (!start.await(5, TimeUnit.SECONDS)) {
            throw new IllegalStateException("Concurrent test failed to synchronize");
        }
        return mvc.perform(post(CASES).header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON).content(request)).andReturn();
    }

    private JsonNode body(MvcResult result) throws Exception {
        return json.readTree(result.getResponse().getContentAsString());
    }
}
