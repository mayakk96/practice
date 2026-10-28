package com.example.practice.events;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.junit.jupiter.api.Test;

class EventMetadataTest {
    @Test
    void acceptsVersionedIdentifierAndStatusMetadata() {
        var event = event(Map.of("status", "CREATED", "applicantId", UUID.randomUUID()));
        assertThat(EventMetadata.validate(event).payload()).containsEntry("status", "CREATED");
    }

    @Test
    void refusesPersonalDataFieldsAndUnrecognizedSchemaVersions() {
        assertThatThrownBy(() -> EventMetadata.validate(event(Map.of("email", "demo@example.com"))))
                .isInstanceOf(InvalidDomainEventException.class)
                .hasMessage("Unsupported event metadata");
        DomainEvent unsupported = new DomainEvent(UUID.randomUUID(), "OnboardingCaseCreated", UUID.randomUUID(),
                Instant.now(), 99, Map.of("status", "CREATED"));
        assertThatThrownBy(() -> EventMetadata.validate(unsupported))
                .isInstanceOf(InvalidDomainEventException.class);
    }

    @Test
    void refusesInvalidEnumValuesAndMissingEnvelopeFields() {
        assertThatThrownBy(() -> EventMetadata.validate(event(Map.of("status", "anything"))))
                .isInstanceOf(InvalidDomainEventException.class);
        assertThatThrownBy(() -> EventMetadata.validate(new DomainEvent(UUID.randomUUID(), null,
                UUID.randomUUID(), Instant.now(), 1, Map.of())))
                .isInstanceOf(InvalidDomainEventException.class);
    }

    private DomainEvent event(Map<String, Object> payload) {
        return new DomainEvent(UUID.randomUUID(), "OnboardingCaseCreated", UUID.randomUUID(), Instant.now(), 1, payload);
    }
}
