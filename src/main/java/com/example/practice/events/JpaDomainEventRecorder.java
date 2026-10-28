package com.example.practice.events;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Clock;
import java.util.Map;
import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

@Service
public class JpaDomainEventRecorder implements DomainEventRecorder {
    private final OutboxEventRepository repository;
    private final ObjectMapper objectMapper;

    public JpaDomainEventRecorder(OutboxEventRepository repository, ObjectMapper objectMapper) {
        this.repository = repository;
        this.objectMapper = objectMapper;
    }

    @Override
    @Transactional(propagation = Propagation.MANDATORY)
    public void record(String eventType, UUID caseId, Map<String, Object> payload) {
        DomainEvent event = EventMetadata.validate(new DomainEvent(
                UUID.randomUUID(), eventType, caseId, Clock.systemUTC().instant(), 1, payload));
        try {
            repository.save(new OutboxEvent(event, objectMapper.writeValueAsString(event)));
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Could not encode domain event", exception);
        }
    }
}
