package com.example.practice.events;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "application.events")
public class EventsProperties {
    @NotBlank
    private String topic = "onboarding.events.v1";

    @Min(1)
    @Max(50)
    private int batchSize = 10;

    @NotNull
    private Duration publishTimeout = Duration.ofSeconds(2);

    @NotNull
    private Duration retryBackoff = Duration.ofSeconds(1);

    public String getTopic() { return topic; }
    public void setTopic(String topic) { this.topic = topic; }
    public int getBatchSize() { return batchSize; }
    public void setBatchSize(int batchSize) { this.batchSize = batchSize; }
    public Duration getPublishTimeout() { return publishTimeout; }
    public void setPublishTimeout(Duration publishTimeout) {
        if (publishTimeout == null || publishTimeout.isZero() || publishTimeout.isNegative()
                || publishTimeout.compareTo(Duration.ofSeconds(10)) > 0) {
            throw new IllegalArgumentException("Event publish timeout must be positive and at most 10 seconds");
        }
        this.publishTimeout = publishTimeout;
    }
    public Duration getRetryBackoff() { return retryBackoff; }
    public void setRetryBackoff(Duration retryBackoff) {
        if (retryBackoff == null || retryBackoff.isNegative() || retryBackoff.isZero()
                || retryBackoff.compareTo(Duration.ofSeconds(30)) > 0) {
            throw new IllegalArgumentException("Event retry backoff must be positive and at most 30 seconds");
        }
        this.retryBackoff = retryBackoff;
    }
}
