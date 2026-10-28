package com.example.practice.screening;

import java.net.URI;
import java.time.Duration;

import jakarta.validation.constraints.AssertTrue;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "application.screening")
public class ScreeningProperties {

    @NotNull
    @Pattern(regexp = "stub|http")
    private String mode = "stub";

    @NotNull
    private URI baseUrl = URI.create("http://localhost:8090");

    @NotNull
    private Duration connectTimeout = Duration.ofMillis(500);

    @NotNull
    private Duration readTimeout = Duration.ofSeconds(1);

    @Min(1)
    @Max(3)
    private int maxAttempts = 3;

    @NotNull
    private Duration backoff = Duration.ofMillis(100);

    @AssertTrue(message = "screening URL must be HTTP(S) without credentials, query, or fragment")
    public boolean isBaseUrlValid() {
        return baseUrl != null && baseUrl.getHost() != null
                && ("http".equals(baseUrl.getScheme()) || "https".equals(baseUrl.getScheme()))
                && baseUrl.getUserInfo() == null && baseUrl.getQuery() == null && baseUrl.getFragment() == null;
    }

    @AssertTrue(message = "screening timeouts must be positive (connect <=5s, read <=10s); backoff must be 0..1s")
    public boolean isTimingValid() {
        return positiveAndAtMost(connectTimeout, Duration.ofSeconds(5))
                && positiveAndAtMost(readTimeout, Duration.ofSeconds(10))
                && backoff != null && !backoff.isNegative() && backoff.compareTo(Duration.ofSeconds(1)) <= 0;
    }

    private boolean positiveAndAtMost(Duration value, Duration maximum) {
        return value != null && !value.isNegative() && !value.isZero() && value.compareTo(maximum) <= 0;
    }

    public String getMode() { return mode; }
    public void setMode(String mode) { this.mode = mode; }
    public URI getBaseUrl() { return baseUrl; }
    public void setBaseUrl(URI baseUrl) { this.baseUrl = baseUrl; }
    public Duration getConnectTimeout() { return connectTimeout; }
    public void setConnectTimeout(Duration connectTimeout) { this.connectTimeout = connectTimeout; }
    public Duration getReadTimeout() { return readTimeout; }
    public void setReadTimeout(Duration readTimeout) { this.readTimeout = readTimeout; }
    public int getMaxAttempts() { return maxAttempts; }
    public void setMaxAttempts(int maxAttempts) { this.maxAttempts = maxAttempts; }
    public Duration getBackoff() { return backoff; }
    public void setBackoff(Duration backoff) { this.backoff = backoff; }
}
