package com.example.practice.events;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;
import java.util.Map;
import java.util.TreeMap;
import org.springframework.dao.DataIntegrityViolationException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.support.TransactionTemplate;

@Service
public class AuditEventService {
    private final AuditEventRepository repository;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transaction;
    private final Counter consumed;
    private final Counter duplicates;

    public AuditEventService(AuditEventRepository repository, ObjectMapper objectMapper,
            PlatformTransactionManager transactionManager, MeterRegistry registry) {
        this.repository = repository;
        this.objectMapper = objectMapper;
        this.transaction = new TransactionTemplate(transactionManager);
        this.transaction.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
        this.consumed = registry.counter("onboarding.events.consumed");
        this.duplicates = registry.counter("onboarding.events.duplicates");
    }

    /** Returns only after the audit transaction commits, so a listener can safely acknowledge. */
    public boolean accept(DomainEvent unvalidated) {
        DomainEvent event = EventMetadata.validate(unvalidated);
        String hash = fingerprint(event);
        boolean inserted;
        try {
            inserted = Boolean.TRUE.equals(transaction.execute(status -> {
                var existing = repository.findById(event.eventId());
                if (existing.isPresent()) {
                    requireSameEvent(existing.get(), hash);
                    return false;
                }
                repository.saveAndFlush(new AuditEvent(event, hash));
                return true;
            }));
        } catch (DataIntegrityViolationException exception) {
            // A concurrent consumer may win the unique-key race. The failed transaction is
            // already rolled back here; querying inside that transaction would be incorrect.
            AuditEvent winner = transaction.execute(status -> repository.findById(event.eventId()).orElse(null));
            if (winner == null) {
                throw exception;
            }
            requireSameEvent(winner, hash);
            inserted = false;
        }
        if (inserted) {
            consumed.increment();
        } else {
            duplicates.increment();
        }
        return inserted;
    }

    private void requireSameEvent(AuditEvent existing, String hash) {
        if (!existing.getPayloadHash().equals(hash)) {
            throw new InvalidDomainEventException("An event identifier was reused with different metadata");
        }
    }

    private String fingerprint(DomainEvent event) {
        try {
            Map<String, Object> canonical = new TreeMap<>();
            canonical.put("eventType", event.eventType());
            canonical.put("caseId", event.caseId().toString());
            canonical.put("occurredAt", event.occurredAt().toString());
            canonical.put("schemaVersion", event.schemaVersion());
            canonical.put("payload", new TreeMap<>(event.payload()));
            byte[] bytes = objectMapper.writeValueAsString(canonical).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(bytes));
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("Could not fingerprint domain event", exception);
        }
    }
}
