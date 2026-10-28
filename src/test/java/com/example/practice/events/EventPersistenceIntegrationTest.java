package com.example.practice.events;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.Callable;
import java.util.concurrent.CyclicBarrier;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.domain.PageRequest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.IllegalTransactionStateException;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@SpringBootTest
@ActiveProfiles("test")
class EventPersistenceIntegrationTest {
    @Autowired private DomainEventRecorder recorder;
    @Autowired private OutboxEventRepository outbox;
    @Autowired private AuditEventRepository audit;
    @Autowired private AuditEventService auditService;
    @Autowired private PlatformTransactionManager transactionManager;
    @Autowired private ObjectMapper mapper;

    @BeforeEach
    void clean() {
        outbox.deleteAll();
        audit.deleteAll();
    }

    @Test
    void requiresBusinessTransactionAndRollsBackItsOutboxWrites() {
        UUID caseId = UUID.randomUUID();
        assertThatThrownBy(() -> recorder.record("OnboardingCaseCreated", caseId, Map.of("status", "CREATED")))
                .isInstanceOf(IllegalTransactionStateException.class);
        assertThatThrownBy(() -> new TransactionTemplate(transactionManager).execute(status -> {
            recorder.record("OnboardingCaseCreated", caseId, Map.of("status", "CREATED"));
            throw new IllegalStateException("Rollback business change");
        })).isInstanceOf(IllegalStateException.class);
        assertThat(outbox.count()).isZero();
    }

    @Test
    void recordsAReadableVersionedEventAndOnlyFirstPendingEventOfEachCaseIsDeliverable() throws Exception {
        UUID caseId = UUID.randomUUID();
        UUID otherCaseId = UUID.randomUUID();
        var transaction = new TransactionTemplate(transactionManager);
        transaction.executeWithoutResult(status -> {
            recorder.record("OnboardingCaseCreated", caseId, Map.of("status", "CREATED"));
            recorder.record("OnboardingStatusChanged", caseId,
                    Map.of("previousStatus", "CREATED", "newStatus", "DOCUMENTS_PENDING"));
            recorder.record("OnboardingCaseCreated", otherCaseId, Map.of("status", "CREATED"));
        });
        assertThat(outbox.count()).isEqualTo(3);
        List<OutboxEvent> deliverable = transaction.execute(status ->
                outbox.lockNextDeliverable(Instant.now(), PageRequest.of(0, 10)));
        assertThat(deliverable).hasSize(2);
        assertThat(deliverable).allMatch(row -> row.getEventType().equals("OnboardingCaseCreated"));
        DomainEvent decoded = mapper.readValue(deliverable.getFirst().getEventJson(), DomainEvent.class);
        assertThat(decoded.schemaVersion()).isEqualTo(1);
        assertThat(decoded.eventId()).isEqualTo(deliverable.getFirst().getId());
        assertThat(decoded.payload()).containsEntry("status", "CREATED");
    }

    @Test
    void replayIsIgnoredButReusingEventIdForDifferentContentIsRejected() {
        DomainEvent event = event();
        assertThat(auditService.accept(event)).isTrue();
        assertThat(auditService.accept(event)).isFalse();
        assertThat(audit.count()).isEqualTo(1);
        DomainEvent changed = new DomainEvent(event.eventId(), event.eventType(), UUID.randomUUID(),
                event.occurredAt(), 1, event.payload());
        assertThatThrownBy(() -> auditService.accept(changed))
                .isInstanceOf(InvalidDomainEventException.class);
        assertThat(audit.count()).isEqualTo(1);
    }

    @Test
    void concurrentDuplicateDeliveryCreatesExactlyOneDurableAuditRecord() throws Exception {
        DomainEvent event = event();
        CyclicBarrier barrier = new CyclicBarrier(2);
        try (var executor = Executors.newFixedThreadPool(2)) {
            Callable<Boolean> consume = () -> {
                barrier.await(5, TimeUnit.SECONDS);
                return auditService.accept(event);
            };
            var results = executor.invokeAll(List.of(consume, consume));
            assertThat(List.of(results.get(0).get(), results.get(1).get())).containsExactlyInAnyOrder(true, false);
        }
        assertThat(audit.count()).isEqualTo(1);
    }

    private DomainEvent event() {
        return new DomainEvent(UUID.randomUUID(), "OnboardingCaseCreated", UUID.randomUUID(),
                Instant.now(), 1, Map.of("status", "CREATED"));
    }
}
