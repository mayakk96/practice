package com.example.practice.events;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.kafka.annotation.KafkaListener;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "application.events", name = "enabled", havingValue = "true")
public class OnboardingAuditConsumer {
    private static final Logger log = LoggerFactory.getLogger(OnboardingAuditConsumer.class);
    private final ObjectMapper objectMapper;
    private final AuditEventService auditService;

    public OnboardingAuditConsumer(ObjectMapper objectMapper, AuditEventService auditService) {
        this.objectMapper = objectMapper;
        this.auditService = auditService;
    }

    @KafkaListener(
            topics = "${application.events.topic:onboarding.events.v1}",
            groupId = "${application.events.consumer-group:onboarding-audit-v1}",
            containerFactory = "onboardingKafkaListenerContainerFactory")
    public void consume(String json) {
        if (json == null || json.length() > 12000) {
            throw new InvalidDomainEventException("Unsupported domain event size");
        }
        try {
            DomainEvent event = objectMapper.readValue(json, DomainEvent.class);
            boolean inserted = auditService.accept(event);
            log.info("audit_event_processed eventId={} caseId={} duplicate={}",
                    event.eventId(), event.caseId(), !inserted);
        } catch (JsonProcessingException exception) {
            throw new InvalidDomainEventException("Malformed domain event JSON");
        }
    }
}
