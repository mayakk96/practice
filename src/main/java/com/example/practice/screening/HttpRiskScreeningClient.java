package com.example.practice.screening;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZonedDateTime;
import java.time.format.DateTimeFormatter;
import java.time.format.DateTimeParseException;
import java.util.Objects;
import java.util.UUID;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

/** Owns provider protocol details, bounded retries, and safe exception translation. */
public final class HttpRiskScreeningClient implements RiskScreeningClient {

    private static final Logger log = LoggerFactory.getLogger(HttpRiskScreeningClient.class);
    private static final Duration MAX_RETRY_DELAY = Duration.ofSeconds(1);
    private final RestClient client;
    private final ScreeningProperties properties;
    private final RetrySleeper sleeper;
    private final Clock clock;

    public HttpRiskScreeningClient(RestClient client, ScreeningProperties properties) {
        this(client, properties, Thread::sleep, Clock.systemUTC());
    }

    HttpRiskScreeningClient(RestClient client, ScreeningProperties properties, RetrySleeper sleeper, Clock clock) {
        this.client = Objects.requireNonNull(client);
        this.properties = Objects.requireNonNull(properties);
        this.sleeper = Objects.requireNonNull(sleeper);
        this.clock = Objects.requireNonNull(clock);
    }

    @Override
    public ScreeningResult screen(UUID caseId) {
        Objects.requireNonNull(caseId, "caseId");
        for (int attempt = 1; attempt <= properties.getMaxAttempts(); attempt++) {
            try {
                ScreeningResult result = client.post().uri("/screenings")
                        .contentType(MediaType.APPLICATION_JSON)
                        .accept(MediaType.APPLICATION_JSON)
                        .header("Idempotency-Key", caseId.toString())
                        .header(HttpHeaders.USER_AGENT, "enterprise-onboarding-portfolio/1.0")
                        .headers(headers -> {
                            String requestId = MDC.get("requestId");
                            if (requestId != null && requestId.matches("[a-zA-Z0-9_-]{1,64}")) {
                                headers.set("X-Request-ID", requestId);
                            }
                        })
                        .body(new ScreeningRequest(caseId))
                        .retrieve().body(ScreeningResult.class);
                return validate(result);
            } catch (RestClientResponseException exception) {
                int status = exception.getStatusCode().value();
                if (status != 429 && !exception.getStatusCode().is5xxServerError()) {
                    // Never preserve the provider body in our exception or logs: it may contain sensitive data.
                    throw new ScreeningRejectedException("Risk provider rejected the request (HTTP " + status + ").");
                }
                Duration delay = retryDelay(attempt, exception.getResponseHeaders());
                retryOrFail(caseId, attempt, "HTTP_" + status, delay);
            } catch (ResourceAccessException exception) {
                retryOrFail(caseId, attempt, "NETWORK", retryDelay(attempt, null));
            } catch (RestClientException exception) {
                throw new ScreeningRejectedException("Risk provider returned an unreadable response.");
            }
        }
        throw new ScreeningUnavailableException("Risk screening is temporarily unavailable.");
    }

    private ScreeningResult validate(ScreeningResult result) {
        if (result == null || result.riskLevel() == null || result.riskLevel() == RiskLevel.NOT_SCREENED
                || result.providerReference() == null
                || !result.providerReference().matches("[A-Za-z0-9_.:-]{1,120}")) {
            throw new ScreeningRejectedException("Risk provider returned an invalid response.");
        }
        return result;
    }

    private void retryOrFail(UUID caseId, int attempt, String category, Duration delay) {
        if (attempt >= properties.getMaxAttempts() || delay.compareTo(MAX_RETRY_DELAY) > 0) {
            log.warn("risk_screening_unavailable caseId={} attempts={} category={}", caseId, attempt, category);
            throw new ScreeningUnavailableException("Risk screening is temporarily unavailable; retry later.");
        }
        log.info("risk_screening_retry caseId={} attempt={} category={} delayMs={}",
                caseId, attempt, category, delay.toMillis());
        try {
            sleeper.sleep(delay);
        } catch (InterruptedException interrupted) {
            Thread.currentThread().interrupt();
            throw new ScreeningUnavailableException("Risk screening was interrupted.");
        }
    }

    private Duration retryDelay(int attempt, HttpHeaders headers) {
        long exponentialMillis = properties.getBackoff().toMillis() * (1L << (attempt - 1));
        Duration exponential = Duration.ofMillis(Math.min(exponentialMillis, MAX_RETRY_DELAY.toMillis()));
        String retryAfter = headers == null ? null : headers.getFirst(HttpHeaders.RETRY_AFTER);
        if (retryAfter == null) {
            return exponential;
        }
        try {
            long seconds = Long.parseLong(retryAfter);
            if (seconds < 0) {
                return exponential;
            }
            // A long Retry-After cannot fit this synchronous operation's retry budget.
            return seconds > 1 ? MAX_RETRY_DELAY.plusMillis(1) : Duration.ofSeconds(seconds);
        } catch (NumberFormatException invalidSeconds) {
            try {
                Instant retryAt = ZonedDateTime.parse(retryAfter, DateTimeFormatter.RFC_1123_DATE_TIME).toInstant();
                Duration remaining = Duration.between(clock.instant(), retryAt);
                return remaining.isNegative() ? Duration.ZERO : remaining;
            } catch (DateTimeParseException invalidDate) {
                return exponential;
            }
        }
    }

    private record ScreeningRequest(UUID caseId) {
    }

    @FunctionalInterface
    interface RetrySleeper {
        void sleep(Duration duration) throws InterruptedException;
    }
}
