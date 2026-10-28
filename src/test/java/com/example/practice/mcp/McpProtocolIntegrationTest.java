package com.example.practice.mcp;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;

import com.example.practice.onboarding.api.CaseResponse;
import com.example.practice.onboarding.api.PageResponse;
import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.service.OnboardingService;
import com.example.practice.screening.RiskLevel;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.web.server.LocalServerPort;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoBean;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.when;

@ActiveProfiles("test")
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT, properties = {
        "spring.ai.mcp.server.protocol=STATELESS", "spring.ai.mcp.server.enabled=true"
})
class McpProtocolIntegrationTest {
    @LocalServerPort
    private int port;

    @Autowired
    private ObjectMapper objectMapper;

    @MockitoBean
    private OnboardingService onboarding;

    @Test
    void performsRealMcpHandshakeListsSafeToolsAndCallsTypedToolsOverHttp() throws Exception {
        UUID caseId = UUID.randomUUID();
        when(onboarding.getCase(caseId)).thenReturn(new CaseResponse(caseId, UUID.randomUUID(), "Demo", "Applicant",
                "fictional@example.com", CaseStatus.CREATED, RiskLevel.NOT_SCREENED, "ONBOARDING", Instant.now(), Instant.now()));
        when(onboarding.listPendingCases(0, 2)).thenReturn(new PageResponse<>(List.of(), 0, 2, 0, 0));

        JsonNode initialized = rpc(1, "initialize", Map.of("protocolVersion", "2025-06-18", "capabilities", Map.of(),
                "clientInfo", Map.of("name", "portfolio-protocol-test", "version", "1.0")));
        assertThat(initialized.path("result").path("protocolVersion").asText()).isNotBlank();
        assertThat(initialized.path("result").path("capabilities").has("tools")).isTrue();
        assertThat(initialized.path("result").path("capabilities").has("resources")).isFalse();
        assertThat(initialized.path("result").path("capabilities").has("prompts")).isFalse();
        assertThat(initialized.path("result").path("capabilities").has("completions")).isFalse();

        JsonNode listed = rpc(2, "tools/list", Map.of());
        List<String> names = new java.util.ArrayList<>();
        listed.path("result").path("tools").forEach(tool -> {
            names.add(tool.path("name").asText());
            assertThat(tool.path("annotations").path("readOnlyHint").asBoolean()).isTrue();
            assertThat(tool.path("inputSchema").path("type").asText()).isEqualTo("object");
        });
        assertThat(names).containsExactlyInAnyOrder("get_onboarding_case", "list_pending_cases",
                "get_case_status_history", "search_onboarding_policy");

        JsonNode called = rpc(3, "tools/call", Map.of("name", "get_onboarding_case", "arguments", Map.of("caseId", caseId.toString())));
        assertThat(called.path("result").path("isError").asBoolean()).isFalse();
        assertThat(called.path("result").path("structuredContent").path("id").asText()).isEqualTo(caseId.toString());
        assertThat(called.toString()).doesNotContain("fictional@example.com", "firstName", "lastName");

        JsonNode pending = rpc(4, "tools/call", Map.of("name", "list_pending_cases", "arguments", Map.of("page", 0, "size", 2)));
        assertThat(pending.path("result").path("structuredContent").path("items").isArray()).isTrue();

        JsonNode invalid = rpc(5, "tools/call", Map.of("name", "get_onboarding_case", "arguments", Map.of("caseId", "invalid")));
        assertThat(invalid.path("result").path("isError").asBoolean()).isTrue();
        assertThat(invalid.path("result").path("structuredContent").path("code").asText()).isEqualTo("INVALID_INPUT");

        JsonNode policy = rpc(6, "tools/call", Map.of("name", "search_onboarding_policy", "arguments",
                Map.of("query", "Which documents are required for approval?", "topK", 2)));
        assertThat(policy.path("result").path("structuredContent").path("citations").isEmpty()).isFalse();
    }

    private JsonNode rpc(int id, String method, Map<String, Object> params) throws Exception {
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:" + port + "/mcp"))
                .timeout(Duration.ofSeconds(10)).header("Content-Type", "application/json")
                .header("Accept", "application/json, text/event-stream")
                .header("MCP-Protocol-Version", "2025-06-18")
                .POST(HttpRequest.BodyPublishers.ofString(objectMapper.writeValueAsString(
                        Map.of("jsonrpc", "2.0", "id", id, "method", method, "params", params))))
                .build();
        try (HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build()) {
            HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
            assertThat(response.statusCode()).isEqualTo(200);
            String body = response.body();
            if (response.headers().firstValue("Content-Type").orElse("").contains("text/event-stream")) {
                body = body.lines().filter(line -> line.startsWith("data:")).map(line -> line.substring(5).strip())
                        .filter(line -> !line.isEmpty()).reduce((left, right) -> right).orElseThrow();
            }
            JsonNode message = objectMapper.readTree(body);
            assertThat(message.has("error")).as("MCP JSON-RPC error: %s", message).isFalse();
            return message;
        }
    }
}
