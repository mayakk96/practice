package com.example.practice.onboarding;

import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.screening.RiskLevel;
import com.example.practice.screening.RiskScreeningClient;
import com.example.practice.screening.ScreeningResult;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.patch;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = "spring.datasource.url=jdbc:h2:mem:review-recovery-test;MODE=PostgreSQL;"
        + "DATABASE_TO_LOWER=TRUE;DEFAULT_NULL_ORDERING=HIGH;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000")
@ActiveProfiles("test")
@AutoConfigureMockMvc
class ReviewRecoveryIntegrationTest {
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
    void screeningSucceeds() {
        when(screening.screen(any(UUID.class))).thenReturn(new ScreeningResult(RiskLevel.LOW, "DEMO-RECOVERY"));
    }

    @ParameterizedTest(name = "{0} can request missing documents and resume approval")
    @EnumSource(value = CaseStatus.class, names = {"UNDER_REVIEW", "RISK_REVIEW"})
    void reviewerCanRequestMissingDocumentsWithoutRejectingTheCase(CaseStatus reviewStatus) throws Exception {
        String created = mvc.perform(post(CASES).contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"firstName":"Demo","lastName":"Recovery","email":"recovery@example.com"}
                                """))
                .andExpect(status().isCreated()).andReturn().getResponse().getContentAsString();
        UUID id = UUID.fromString(json.readTree(created).path("id").asText());
        transition(id, CaseStatus.DOCUMENTS_PENDING, "Start fictional document collection");
        transition(id, CaseStatus.UNDER_REVIEW, "Begin review");
        if (reviewStatus == CaseStatus.RISK_REVIEW) {
            transition(id, CaseStatus.RISK_REVIEW, "Request specialist risk review");
        }

        Long historyBefore = historyCount(id);
        mvc.perform(patch(CASES + "/{id}/status", id).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("status", "APPROVED", "reason", "Attempt approval"))))
                .andExpect(status().isConflict())
                .andExpect(jsonPath("$.status").value(409));
        assertThat(historyCount(id)).isEqualTo(historyBefore);
        mvc.perform(get(CASES + "/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value(reviewStatus.name()));

        transition(id, CaseStatus.DOCUMENTS_PENDING, "Additional fictional documents requested");
        submit(id, "IDENTITY_PROOF", "DEMO-RECOVERY-IDENTITY");
        submit(id, "ADDRESS_PROOF", "DEMO-RECOVERY-ADDRESS");
        transition(id, CaseStatus.UNDER_REVIEW, "Additional documents received");
        transition(id, CaseStatus.APPROVED, "Required documents and screening passed");

        mvc.perform(get(CASES + "/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("APPROVED"))
                .andExpect(jsonPath("$.riskLevel").value("LOW"));
        verify(screening).screen(id);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM case_document WHERE case_id = ?", Long.class, id))
                .isEqualTo(2);
        assertThat(historyCount(id)).isEqualTo(historyBefore + 3);
        JsonNode history = json.readTree(mvc.perform(get(CASES + "/{id}/history", id))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        List<JsonNode> entries = new ArrayList<>();
        history.forEach(entries::add);
        assertThat(entries).anySatisfy(entry -> {
            assertThat(entry.path("previousStatus").asText()).isEqualTo(reviewStatus.name());
            assertThat(entry.path("newStatus").asText()).isEqualTo("DOCUMENTS_PENDING");
            assertThat(entry.path("reason").asText()).isEqualTo("Additional fictional documents requested");
            assertThat(entry.path("changedAt").asText()).isNotBlank();
        });
    }

    private void transition(UUID id, CaseStatus target, String reason) throws Exception {
        mvc.perform(patch(CASES + "/{id}/status", id).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("status", target.name(), "reason", reason))))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value(target.name()));
    }

    private void submit(UUID id, String documentType, String reference) throws Exception {
        mvc.perform(post(CASES + "/{id}/documents", id).contentType(MediaType.APPLICATION_JSON)
                        .content(json.writeValueAsString(Map.of("documentType", documentType, "reference", reference))))
                .andExpect(status().isCreated());
    }

    private Long historyCount(UUID id) {
        return jdbc.queryForObject("SELECT count(*) FROM status_history WHERE case_id = ?", Long.class, id);
    }
}
