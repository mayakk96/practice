package com.example.practice.events;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CompletableFuture;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.support.SendResult;

@ExtendWith(MockitoExtension.class)
class OutboxDeliveryServiceTest {
    @Mock
    private OutboxEventRepository repository;
    @Mock
    private KafkaTemplate<String, String> kafka;
    private OutboxDeliveryService service;
    private SimpleMeterRegistry registry;

    @BeforeEach
    void setUp() {
        registry = new SimpleMeterRegistry();
        service = new OutboxDeliveryService(repository, kafka, new EventsProperties(), registry);
    }

    @Test
    void marksPublishedOnlyAfterBrokerAcknowledgementAndKeysByCase() {
        OutboxEvent event = event();
        when(repository.lockNextDeliverable(any(), any())).thenReturn(List.of(event));
        when(kafka.send(anyString(), anyString(), anyString()))
                .thenReturn(CompletableFuture.completedFuture(new SendResult<>(null, null)));

        assertThat(service.deliverNext()).isTrue();

        assertThat(event.getPublishedAt()).isNotNull();
        assertThat(event.getAttempts()).isEqualTo(1);
        verify(kafka).send("onboarding.events.v1", event.getCaseId().toString(), event.getEventJson());
        assertThat(registry.counter("onboarding.events.published").count()).isEqualTo(1);
    }

    @Test
    void brokerFailureKeepsEventPendingAndSchedulesRetryWithoutLoggingExceptionText() {
        OutboxEvent event = event();
        when(repository.lockNextDeliverable(any(), any())).thenReturn(List.of(event));
        when(kafka.send(anyString(), anyString(), anyString()))
                .thenReturn(CompletableFuture.failedFuture(new IllegalStateException("sensitive broker detail")));

        service.deliverNext();

        assertThat(event.getPublishedAt()).isNull();
        assertThat(event.getAttempts()).isEqualTo(1);
        assertThat(event.getLastFailure()).isEqualTo("BROKER_UNAVAILABLE");
        assertThat(event.getNextAttemptAt()).isAfter(Instant.now());
        assertThat(registry.counter("onboarding.events.publish.failures").count()).isEqualTo(1);
    }

    @Test
    void boundsWaitForMissingAcknowledgement() {
        OutboxEvent event = event();
        EventsProperties properties = new EventsProperties();
        properties.setPublishTimeout(java.time.Duration.ofMillis(10));
        service = new OutboxDeliveryService(repository, kafka, properties, registry);
        when(repository.lockNextDeliverable(any(), any())).thenReturn(List.of(event));
        when(kafka.send(anyString(), anyString(), anyString())).thenReturn(new CompletableFuture<>());

        service.deliverNext();

        assertThat(event.getPublishedAt()).isNull();
        assertThat(event.getLastFailure()).isEqualTo("BROKER_TIMEOUT");
    }

    @Test
    void doesNotContactBrokerWhenNoEventIsDue() {
        when(repository.lockNextDeliverable(any(), any())).thenReturn(List.of());
        assertThat(service.deliverNext()).isFalse();
        verifyNoInteractions(kafka);
    }

    private OutboxEvent event() {
        DomainEvent event = new DomainEvent(UUID.randomUUID(), "OnboardingCaseCreated", UUID.randomUUID(),
                Instant.now(), 1, Map.of("status", "CREATED"));
        return new OutboxEvent(event, "{\"test\":true}");
    }
}
