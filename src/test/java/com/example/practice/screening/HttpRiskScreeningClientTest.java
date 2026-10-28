package com.example.practice.screening;

import java.net.SocketTimeoutException;
import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

import jakarta.validation.Validation;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.boot.test.context.runner.ApplicationContextRunner;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.ExpectedCount;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withException;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class HttpRiskScreeningClientTest {
    private static final UUID CASE_ID = UUID.fromString("ce7a9760-42a9-46f0-b40a-5bb833dece10");
    private static final String ENDPOINT = "http://risk.example.test/screenings";
    private static final String VALID_RESPONSE = "{\"riskLevel\":\"LOW\",\"providerReference\":\"provider-123\"}";
    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-01-01T00:00:00Z"), ZoneOffset.UTC);

    private ScreeningProperties properties;
    private MockRestServiceServer server;
    private RestClient restClient;
    private HttpRiskScreeningClient client;
    private List<Duration> delays;

    @BeforeEach
    void setUp() {
        properties = new ScreeningProperties();
        delays = new ArrayList<>();
        RestClient.Builder builder = RestClient.builder().baseUrl("http://risk.example.test");
        server = MockRestServiceServer.bindTo(builder).build();
        restClient = builder.build();
        client = new HttpRiskScreeningClient(restClient, properties, delays::add, CLOCK);
    }

    @AfterEach
    void verifyProviderCalls() {
        server.verify();
    }

    @Test
    void serializesOnlyTheCaseIdAndUsesStableIdempotencyAndProtocolHeaders() {
        server.expect(requestTo(ENDPOINT))
                .andExpect(method(HttpMethod.POST))
                .andExpect(header("Idempotency-Key", CASE_ID.toString()))
                .andExpect(header(HttpHeaders.USER_AGENT, "enterprise-onboarding-portfolio/1.0"))
                .andExpect(header(HttpHeaders.ACCEPT, MediaType.APPLICATION_JSON_VALUE))
                .andExpect(content().contentType(MediaType.APPLICATION_JSON))
                .andExpect(content().json("{\"caseId\":\"" + CASE_ID + "\"}"))
                .andRespond(withSuccess(VALID_RESPONSE, MediaType.APPLICATION_JSON));

        assertThat(client.screen(CASE_ID)).isEqualTo(new ScreeningResult(RiskLevel.LOW, "provider-123"));
        assertThat(delays).isEmpty();
    }

    @Test
    void retriesServerFailuresWithExponentialBackoffAndTheSameIdempotencyKey() {
        server.expect(requestTo(ENDPOINT)).andExpect(header("Idempotency-Key", CASE_ID.toString()))
                .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        server.expect(requestTo(ENDPOINT)).andExpect(header("Idempotency-Key", CASE_ID.toString()))
                .andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR));
        server.expect(requestTo(ENDPOINT)).andExpect(header("Idempotency-Key", CASE_ID.toString()))
                .andRespond(withSuccess(VALID_RESPONSE, MediaType.APPLICATION_JSON));

        assertThat(client.screen(CASE_ID).riskLevel()).isEqualTo(RiskLevel.LOW);
        assertThat(delays).containsExactly(Duration.ofMillis(100), Duration.ofMillis(200));
    }

    @Test
    void translatesAnExhaustedProviderFailureWithoutLeakingItsBody() {
        server.expect(ExpectedCount.times(3), requestTo(ENDPOINT))
                .andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE)
                        .body("provider-private-diagnostic").contentType(MediaType.TEXT_PLAIN));

        assertThatThrownBy(() -> client.screen(CASE_ID))
                .isInstanceOf(ScreeningUnavailableException.class)
                .hasMessage("Risk screening is temporarily unavailable; retry later.")
                .hasNoCause();
        assertThat(delays).hasSize(2);
    }

    @ParameterizedTest
    @ValueSource(ints = {400, 401, 403, 404, 422})
    void neverRetriesPermanentClientErrors(int status) {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.valueOf(status))
                .body("provider-private-diagnostic").contentType(MediaType.TEXT_PLAIN));

        assertThatThrownBy(() -> client.screen(CASE_ID))
                .isInstanceOf(ScreeningRejectedException.class)
                .hasMessage("Risk provider rejected the request (HTTP " + status + ").")
                .hasNoCause();
        assertThat(delays).isEmpty();
    }

    @Test
    void retriesRateLimitingWhenRetryAfterFitsTheSynchronousBudget() {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS)
                .header(HttpHeaders.RETRY_AFTER, "1"));
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess(VALID_RESPONSE, MediaType.APPLICATION_JSON));

        assertThat(client.screen(CASE_ID).riskLevel()).isEqualTo(RiskLevel.LOW);
        assertThat(delays).containsExactly(Duration.ofSeconds(1));
    }

    @Test
    void doesNotRetryEarlierThanALongProviderRetryAfter() {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.TOO_MANY_REQUESTS)
                .header(HttpHeaders.RETRY_AFTER, "60"));

        assertThatThrownBy(() -> client.screen(CASE_ID)).isInstanceOf(ScreeningUnavailableException.class);
        assertThat(delays).isEmpty();
    }

    @Test
    void understandsAnHttpDateRetryAfter() {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE)
                .header(HttpHeaders.RETRY_AFTER, "Thu, 1 Jan 2026 00:00:01 GMT"));
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess(VALID_RESPONSE, MediaType.APPLICATION_JSON));

        client.screen(CASE_ID);

        assertThat(delays).containsExactly(Duration.ofSeconds(1));
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "{broken", "{}", "{\"riskLevel\":\"NOT_SCREENED\",\"providerReference\":\"ref\"}",
            "{\"riskLevel\":\"UNRECOGNIZED\",\"providerReference\":\"ref\"}",
            "{\"riskLevel\":\"LOW\",\"providerReference\":\"unsafe reference\\n\"}"
    })
    void rejectsMalformedOrInvalidResponsesWithoutRetry(String body) {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess(body, MediaType.APPLICATION_JSON));

        assertThatThrownBy(() -> client.screen(CASE_ID))
                .isInstanceOf(ScreeningRejectedException.class).hasNoCause();
        assertThat(delays).isEmpty();
    }

    @Test
    void retriesTransportFailuresButStopsAtTheConfiguredLimit() {
        server.expect(ExpectedCount.times(3), requestTo(ENDPOINT))
                .andRespond(withException(new SocketTimeoutException("private network details")));

        assertThatThrownBy(() -> client.screen(CASE_ID))
                .isInstanceOf(ScreeningUnavailableException.class).hasNoCause();
        assertThat(delays).containsExactly(Duration.ofMillis(100), Duration.ofMillis(200));
    }

    @Test
    void preservesInterruptionInsteadOfContinuingRetryWork() {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.SERVICE_UNAVAILABLE));
        HttpRiskScreeningClient interruptedClient = new HttpRiskScreeningClient(restClient, properties,
                duration -> { throw new InterruptedException("cancelled"); }, CLOCK);

        try {
            assertThatThrownBy(() -> interruptedClient.screen(CASE_ID))
                    .isInstanceOf(ScreeningUnavailableException.class).hasMessage("Risk screening was interrupted.");
            assertThat(Thread.currentThread().isInterrupted()).isTrue();
        } finally {
            Thread.interrupted();
        }
    }

    @Test
    void rejectsUnboundedTimingAndCredentialBearingUrlsInConfiguration() {
        properties.setReadTimeout(Duration.ofMinutes(1));
        properties.setBaseUrl(java.net.URI.create("https://user:password@risk.example.test"));
        try (var factory = Validation.buildDefaultValidatorFactory()) {
            assertThat(factory.getValidator().validate(properties))
                    .extracting(violation -> violation.getPropertyPath().toString())
                    .contains("timingValid", "baseUrlValid");
        }
    }

    @Test
    void defaultsToAnExplicitDeterministicStubWithoutAnyHttpCalls() {
        new ApplicationContextRunner().withUserConfiguration(ScreeningConfiguration.class)
                .run(context -> {
                    assertThat(context).hasSingleBean(RiskScreeningClient.class);
                    assertThat(context.getBean(RiskScreeningClient.class).screen(CASE_ID))
                            .isEqualTo(new ScreeningResult(RiskLevel.LOW, "stub-" + CASE_ID));
                });
    }
}
