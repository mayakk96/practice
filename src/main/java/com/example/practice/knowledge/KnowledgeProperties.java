package com.example.practice.knowledge;

import java.net.URI;
import java.time.Duration;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("application.knowledge")
public record KnowledgeProperties(
        @NotBlank String mode,
        @NotNull URI baseUrl,
        String apiKey,
        @NotBlank String model,
        @NotNull Duration connectTimeout,
        @NotNull Duration readTimeout) {
    public KnowledgeProperties {
        mode = mode == null ? "deterministic" : mode;
        baseUrl = baseUrl == null ? URI.create("http://localhost:11434/v1") : baseUrl;
        model = model == null ? "local-model" : model;
        connectTimeout = connectTimeout == null ? Duration.ofSeconds(1) : connectTimeout;
        readTimeout = readTimeout == null ? Duration.ofSeconds(5) : readTimeout;
        if (!mode.equals("deterministic") && !mode.equals("http")) {
            throw new IllegalArgumentException("Knowledge mode must be deterministic or http");
        }
        if (connectTimeout.isZero() || connectTimeout.isNegative() || connectTimeout.compareTo(Duration.ofSeconds(10)) > 0
                || readTimeout.isZero() || readTimeout.isNegative() || readTimeout.compareTo(Duration.ofSeconds(30)) > 0) {
            throw new IllegalArgumentException("Knowledge model timeouts must be positive and bounded");
        }
    }

    @Override
    public String toString() {
        return "KnowledgeProperties[mode=" + mode + ", model=" + model + ", credentials=redacted]";
    }
}
