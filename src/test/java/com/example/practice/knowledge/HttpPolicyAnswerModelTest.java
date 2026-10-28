package com.example.practice.knowledge;

import java.util.List;

import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withBadRequest;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class HttpPolicyAnswerModelTest {
    @Test
    void sendsBoundedGroundedContextToTheConfiguredModel() {
        RestClient.Builder builder = RestClient.builder().baseUrl("https://model.example.test/v1")
                .defaultHeader("Authorization", "Bearer test-only-fake-value");
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("https://model.example.test/v1/chat/completions"))
                .andExpect(method(HttpMethod.POST)).andExpect(header("Authorization", "Bearer test-only-fake-value"))
                .andExpect(content().json("""
                        {"model":"demo-model","max_tokens":400,"temperature":0.0}
                        """))
                .andRespond(withSuccess("""
                        {"choices":[{"message":{"role":"assistant","content":"Two documents [approval#1]."}}]}
                        """, MediaType.APPLICATION_JSON));
        HttpPolicyAnswerModel model = new HttpPolicyAnswerModel(builder.build(), "demo-model");

        String answer = model.answer("Required documents?", "[approval#1] Two documents.",
                List.of(new PolicyChunk("approval#1", "approval", "Two documents.")));

        assertThat(answer).contains("[approval#1]");
        server.verify();
    }

    @Test
    void providerErrorsAreSanitizedAndNotRetried() {
        RestClient.Builder builder = RestClient.builder().baseUrl("https://model.example.test/v1");
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("https://model.example.test/v1/chat/completions"))
                .andRespond(withBadRequest().body("sensitive-provider-response"));

        assertThatThrownBy(() -> new HttpPolicyAnswerModel(builder.build(), "demo").answer("question", "context", List.of()))
                .isInstanceOf(KnowledgeUnavailableException.class).hasMessageNotContaining("sensitive-provider-response");
        server.verify();
    }

    @Test
    void malformedModelOutputIsNotPresentedAsAnAnswer() {
        RestClient.Builder builder = RestClient.builder().baseUrl("https://model.example.test/v1");
        MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
        server.expect(requestTo("https://model.example.test/v1/chat/completions"))
                .andRespond(withSuccess("{\"choices\":[]}", MediaType.APPLICATION_JSON));
        assertThatThrownBy(() -> new HttpPolicyAnswerModel(builder.build(), "demo").answer("question", "context", List.of()))
                .isInstanceOf(KnowledgeUnavailableException.class);
        server.verify();
    }
}
