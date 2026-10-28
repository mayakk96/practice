package com.example.practice.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.util.UUID;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.MethodSource;
import org.slf4j.MDC;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import static org.assertj.core.api.Assertions.assertThat;
import static org.springframework.security.test.web.servlet.request.SecurityMockMvcRequestPostProcessors.httpBasic;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(properties = {
        "application.security.enabled=true",
        "spring.datasource.url=jdbc:h2:mem:security-test;MODE=PostgreSQL;DATABASE_TO_LOWER=TRUE;"
                + "DEFAULT_NULL_ORDERING=HIGH;DB_CLOSE_DELAY=-1;LOCK_TIMEOUT=10000"
})
@ActiveProfiles("test")
@AutoConfigureMockMvc
class SecurityIntegrationTest {
    private static final String OPERATOR = "test-operator";
    private static final String READER = "test-reader";
    // Credentials are generated per test JVM and never become application defaults.
    private static final String OPERATOR_PASSWORD = UUID.randomUUID().toString();
    private static final String READER_PASSWORD = UUID.randomUUID().toString();

    @DynamicPropertySource
    static void credentials(DynamicPropertyRegistry registry) {
        registry.add("application.security.username", () -> OPERATOR);
        registry.add("application.security.password", () -> OPERATOR_PASSWORD);
        registry.add("application.security.read-only-username", () -> READER);
        registry.add("application.security.read-only-password", () -> READER_PASSWORD);
    }

    @Autowired
    private MockMvc mvc;

    @Autowired
    private ObjectMapper mapper;

    @Test
    void healthIsPublicWithoutExposingDatabaseDetails() throws Exception {
        mvc.perform(get("/actuator/health"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.status").value("UP"))
                .andExpect(jsonPath("$.components").doesNotExist())
                .andExpect(header().exists("X-Request-ID"));
    }

    @Test
    void anonymousApiRequestsReceiveProblemDetailsWithCorrelationId() throws Exception {
        String requestId = "security-authentication-42";
        mvc.perform(get("/api/onboarding/cases").header("X-Request-ID", requestId))
                .andExpect(status().isUnauthorized())
                .andExpect(header().string("WWW-Authenticate", "Basic realm=\"onboarding\""))
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(401))
                .andExpect(jsonPath("$.detail").value("Valid API credentials are required."))
                .andExpect(header().string("X-Request-ID", requestId))
                .andExpect(jsonPath("$.requestId").value(requestId));
        assertThat(MDC.get("requestId")).isNull();
    }

    @Test
    void operatorCanCreateCases() throws Exception {
        mvc.perform(post("/api/onboarding/cases")
                        .with(httpBasic(OPERATOR, OPERATOR_PASSWORD))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"firstName":"Demo","lastName":"Operator", "email":"operator@example.com"}
                                """))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.id").isString())
                .andExpect(jsonPath("$.status").value("CREATED"));
    }

    @Test
    void readerCanReadCasesButCannotCreateThem() throws Exception {
        mvc.perform(get("/api/onboarding/cases").with(httpBasic(READER, READER_PASSWORD)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.items").isArray());

        String requestId = "reader-denied-request";
        mvc.perform(post("/api/onboarding/cases")
                        .with(httpBasic(READER, READER_PASSWORD))
                        .header("X-Request-ID", requestId)
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"firstName":"Demo","lastName":"Reader", "email":"reader@example.com"}
                                """))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(403))
                .andExpect(jsonPath("$.requestId").value(requestId))
                .andExpect(header().string("X-Request-ID", requestId));
    }

    @Test
    void readerCanUseReadOnlyKnowledgeSearch() throws Exception {
        mvc.perform(post("/api/knowledge/search")
                        .with(httpBasic(READER, READER_PASSWORD))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"query":"Which documents are required before approval?","topK":2}
                                """))
                .andExpect(status().isOk());
    }

    @Test
    void mcpRequiresAuthenticationBeforeProcessingProtocolMessages() throws Exception {
        mvc.perform(post("/mcp")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("""
                                {"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
                                """))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(jsonPath("$.status").value(401));
    }

    @Test
    void onlyOperatorCanAccessMetrics() throws Exception {
        mvc.perform(get("/actuator/metrics").with(httpBasic(READER, READER_PASSWORD)))
                .andExpect(status().isForbidden());
        mvc.perform(get("/actuator/metrics").with(httpBasic(OPERATOR, OPERATOR_PASSWORD)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.names").isArray());
    }

    @Test
    void controllerErrorsRetainTheSuppliedSafeCorrelationId() throws Exception {
        String requestId = "read-case-request_2026";
        mvc.perform(get("/api/onboarding/cases/{id}", UUID.randomUUID())
                        .with(httpBasic(READER, READER_PASSWORD))
                        .header("X-Request-ID", requestId))
                .andExpect(status().isNotFound())
                .andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_PROBLEM_JSON))
                .andExpect(header().string("X-Request-ID", requestId))
                .andExpect(jsonPath("$.requestId").value(requestId));
        assertThat(MDC.get("requestId")).isNull();
    }

    @ParameterizedTest
    @MethodSource("unsafeRequestIds")
    void unsafeCorrelationIdsAreReplacedAndNeverReflected(String supplied) throws Exception {
        var result = mvc.perform(get("/api/onboarding/cases").header("X-Request-ID", supplied))
                .andExpect(status().isUnauthorized())
                .andExpect(jsonPath("$.status").value(401))
                .andReturn();
        String generated = result.getResponse().getHeader("X-Request-ID");
        assertThat(generated).isNotEqualTo(supplied);
        assertThat(UUID.fromString(generated).toString()).isEqualTo(generated);
        assertThat(mapper.readTree(result.getResponse().getContentAsString()).path("requestId").asText())
                .isEqualTo(generated);
        assertThat(MDC.get("requestId")).isNull();
    }

    static Stream<String> unsafeRequestIds() {
        return Stream.of("bad request id", "unsafe\r\nforged-header: injected", "x".repeat(65));
    }
}
