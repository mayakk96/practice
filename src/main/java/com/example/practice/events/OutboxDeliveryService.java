package com.example.practice.events;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Instant;
import java.util.concurrent.ExecutionException;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.domain.PageRequest;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
@ConditionalOnProperty(prefix = "application.events", name = "enabled", havingValue = "true")
public class OutboxDeliveryService {
    private static final Logger log = LoggerFactory.getLogger(OutboxDeliveryService.class);
    private final OutboxEventRepository repository;
    private final KafkaTemplate<String, String> template;
    private final EventsProperties properties;
    private final Counter published;
    private final Counter failed;

    public OutboxDeliveryService(OutboxEventRepository repository, KafkaTemplate<String, String> template,
            EventsProperties properties, MeterRegistry registry) {
        this.repository = repository;
        this.template = template;
        this.properties = properties;
        this.published = registry.counter("onboarding.events.published");
        this.failed = registry.counter("onboarding.events.publish.failures");
    }

    /** One bounded database transaction per event, never one transaction around an entire batch. */
    @Transactional(timeout = 15)
    public boolean deliverNext() {
        var candidates = repository.lockNextDeliverable(Instant.now(), PageRequest.of(0, 1));
        if (candidates.isEmpty()) {
            return false;
        }
        OutboxEvent event = candidates.getFirst();
        try {
            template.send(properties.getTopic(), event.getCaseId().toString(), event.getEventJson())
                    .get(properties.getPublishTimeout().toMillis(), TimeUnit.MILLISECONDS);
            event.delivered(Instant.now());
            published.increment();
            log.info("event_published eventId={} caseId={} eventType={}",
                    event.getId(), event.getCaseId(), event.getEventType());
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            markFailure(event, "PUBLISH_INTERRUPTED");
        } catch (TimeoutException exception) {
            markFailure(event, "BROKER_TIMEOUT");
        } catch (ExecutionException | RuntimeException exception) {
            markFailure(event, "BROKER_UNAVAILABLE");
        }
        return true;
    }

    private void markFailure(OutboxEvent event, String classification) {
        long multiplier = 1L << Math.min(event.getAttempts(), 6);
        long delayMillis = Math.min(properties.getRetryBackoff().toMillis() * multiplier, 60_000L);
        event.failed(Instant.now().plusMillis(delayMillis), classification);
        failed.increment();
        log.warn("event_publish_failed eventId={} caseId={} classification={} attempts={}",
                event.getId(), event.getCaseId(), classification, event.getAttempts());
    }
}
