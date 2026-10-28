package com.example.practice.events;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.doAnswer;
import static org.mockito.Mockito.mockingDetails;

import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.mockito.stubbing.Answer;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.context.bean.override.mockito.MockitoSpyBean;

/** Forces the window between the first existence check and the actual database insert. */
@SpringBootTest
@ActiveProfiles("test")
class AuditInsertRaceIntegrationTest {
    @MockitoSpyBean
    private AuditEventRepository repository;

    @Autowired
    private AuditEventService service;

    @BeforeEach
    void clean() {
        repository.deleteAll();
    }

    @ParameterizedTest(name = "a paused insert cannot overwrite the winner; conflicting payload = {0}")
    @ValueSource(booleans = {false, true})
    void assignedEventIdsAlwaysInsertInsteadOfMergingOverAnAlreadyCommittedWinner(boolean conflicting)
            throws Exception {
        UUID eventId = UUID.randomUUID();
        UUID caseId = UUID.randomUUID();
        Instant occurredAt = Instant.now();
        DomainEvent winner = new DomainEvent(eventId, "OnboardingCaseCreated", caseId,
                occurredAt, 1, Map.of("status", "CREATED"));
        DomainEvent delayed = new DomainEvent(eventId, "OnboardingCaseCreated",
                conflicting ? UUID.randomUUID() : caseId, occurredAt, 1, Map.of("status", "CREATED"));
        CountDownLatch pausedBeforeInsert = new CountDownLatch(1);
        CountDownLatch winnerCommitted = new CountDownLatch(1);
        AtomicBoolean pauseFirstSave = new AtomicBoolean(true);
        // The spy wraps a Spring Data interface proxy. Preserve its delegate answer;
        // callRealMethod() would try to invoke the abstract repository method itself.
        Answer<?> realRepository = mockingDetails(repository).getMockCreationSettings().getDefaultAnswer();

        doAnswer(invocation -> {
            if (pauseFirstSave.compareAndSet(true, false)) {
                pausedBeforeInsert.countDown();
                if (!winnerCommitted.await(10, TimeUnit.SECONDS)) {
                    throw new AssertionError("The winner did not commit while the first insert was paused");
                }
            }
            return realRepository.answer(invocation);
        }).when(repository).saveAndFlush(any(AuditEvent.class));

        try (var executor = Executors.newSingleThreadExecutor()) {
            var delayedResult = executor.submit(() -> service.accept(delayed));
            try {
                assertThat(pausedBeforeInsert.await(10, TimeUnit.SECONDS)).isTrue();
                assertThat(service.accept(winner)).isTrue();
                AuditEvent original = repository.findById(eventId).orElseThrow();
                String originalHash = original.getPayloadHash();
                winnerCommitted.countDown();

                if (conflicting) {
                    assertThatThrownBy(() -> delayedResult.get(10, TimeUnit.SECONDS))
                            .hasCauseInstanceOf(InvalidDomainEventException.class);
                } else {
                    assertThat(delayedResult.get(10, TimeUnit.SECONDS)).isFalse();
                }

                assertThat(repository.count()).isEqualTo(1);
                AuditEvent retained = repository.findById(eventId).orElseThrow();
                assertThat(retained.getCaseId()).isEqualTo(caseId);
                assertThat(retained.getPayloadHash()).isEqualTo(originalHash);
            } finally {
                winnerCommitted.countDown();
            }
        }
    }
}
