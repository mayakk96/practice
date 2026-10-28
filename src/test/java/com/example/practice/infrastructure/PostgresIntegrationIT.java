package com.example.practice.infrastructure;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.MvcResult;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Run explicitly with ./mvnw -Ppostgres-it verify; Docker is a required prerequisite. */
@Testcontainers
@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
class PostgresIntegrationIT {

    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:17-alpine")
            .withDatabaseName("onboarding");

    @DynamicPropertySource
    static void postgresProperties(DynamicPropertyRegistry properties) {
        properties.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        properties.add("spring.datasource.username", POSTGRES::getUsername);
        properties.add("spring.datasource.password", POSTGRES::getPassword);
        properties.add("spring.datasource.driver-class-name", () -> "org.postgresql.Driver");
    }

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper json;

    @Autowired
    private JdbcTemplate jdbc;

    @Test
    void flywayCreatesTheRealPostgresSchemaAndQueryIndexes() {
        assertThat(jdbc.queryForObject("SELECT current_database()", String.class)).isEqualTo("onboarding");
        List<String> versions = jdbc.queryForList(
                "SELECT version FROM flyway_schema_history WHERE success = true ORDER BY installed_rank", String.class);
        assertThat(versions).contains("1", "2", "3");
        List<String> indexes = jdbc.queryForList(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public'", String.class);
        assertThat(indexes).contains("ix_case_applicant", "ix_case_created", "ix_case_status", "idx_outbox_pending");
        assertThat(jdbc.queryForObject("SELECT count(*) FROM information_schema.table_constraints "
                + "WHERE constraint_schema = 'public' AND constraint_type = 'FOREIGN KEY'", Long.class))
                .isGreaterThanOrEqualTo(3);
    }

    @Test
    void apiWritesAndReadsCommittedRowsAndReplaysCreationOnPostgres() throws Exception {
        String key = UUID.randomUUID().toString();
        String request = "{\"firstName\":\"Demo\",\"lastName\":\"Postgres\",\"email\":\"postgres@example.com\"}";
        var created = mvc.perform(post("/api/onboarding/cases").header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isCreated()).andReturn();
        JsonNode body = json.readTree(created.getResponse().getContentAsString());
        UUID id = UUID.fromString(body.path("id").asText());

        mvc.perform(get("/api/onboarding/cases/{id}", id))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.email").value("postgres@example.com"));
        mvc.perform(post("/api/onboarding/cases").header("Idempotency-Key", key)
                        .contentType(MediaType.APPLICATION_JSON).content(request))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.id").value(id.toString()));
        assertThat(jdbc.queryForObject("SELECT count(*) FROM onboarding_case WHERE id = ?", Long.class, id)).isEqualTo(1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM event_outbox WHERE case_id = ?", Long.class, id))
                .isEqualTo(1);
    }

    @Test
    void postgresRejectsAnOrphanedCaseAtTheDatabaseBoundary() {
        assertThatThrownBy(() -> jdbc.update("INSERT INTO onboarding_case "
                        + "(id, applicant_id, status, risk_level, assigned_team, created_at, updated_at, version) "
                        + "VALUES (?, ?, 'CREATED', 'NOT_SCREENED', 'ONBOARDING', current_timestamp, current_timestamp, 0)",
                UUID.randomUUID(), UUID.randomUUID()))
                .isInstanceOf(DataIntegrityViolationException.class);
    }

    @Test
    void concurrentIdempotentRequestsRecoverFromPostgresUniqueViolationWithoutOrphanRows() throws Exception {
        String key = UUID.randomUUID().toString();
        String request = "{\"firstName\":\"Demo\",\"lastName\":\"Concurrent\",\"email\":\"concurrent@example.com\"}";
        long casesBefore = count("onboarding_case");
        long applicantsBefore = count("applicant");
        long eventsBefore = count("event_outbox");
        CountDownLatch ready = new CountDownLatch(2);
        CountDownLatch start = new CountDownLatch(1);

        try (var executor = Executors.newFixedThreadPool(2)) {
            var first = executor.submit(() -> createTogether(key, request, ready, start));
            var second = executor.submit(() -> createTogether(key, request, ready, start));
            assertThat(ready.await(5, TimeUnit.SECONDS)).isTrue();
            start.countDown();
            MvcResult firstResult = first.get(20, TimeUnit.SECONDS);
            MvcResult secondResult = second.get(20, TimeUnit.SECONDS);
            assertThat(List.of(firstResult.getResponse().getStatus(), secondResult.getResponse().getStatus()))
                    .containsExactlyInAnyOrder(201, 200);
            assertThat(json.readTree(firstResult.getResponse().getContentAsString()).path("id").asText())
                    .isEqualTo(json.readTree(secondResult.getResponse().getContentAsString()).path("id").asText());
        }

        assertThat(count("onboarding_case")).isEqualTo(casesBefore + 1);
        assertThat(count("applicant")).isEqualTo(applicantsBefore + 1);
        assertThat(count("event_outbox")).isEqualTo(eventsBefore + 1);
        assertThat(jdbc.queryForObject("SELECT count(*) FROM idempotency_request WHERE request_key = ?", Long.class, key))
                .isEqualTo(1);
    }

    private MvcResult createTogether(String key, String request, CountDownLatch ready, CountDownLatch start)
            throws Exception {
        ready.countDown();
        if (!start.await(5, TimeUnit.SECONDS)) {
            throw new IllegalStateException("Concurrent PostgreSQL test failed to synchronize");
        }
        return mvc.perform(post("/api/onboarding/cases").header("Idempotency-Key", key)
                .contentType(MediaType.APPLICATION_JSON).content(request)).andReturn();
    }

    private long count(String table) {
        return jdbc.queryForObject("SELECT count(*) FROM " + table, Long.class);
    }
}
