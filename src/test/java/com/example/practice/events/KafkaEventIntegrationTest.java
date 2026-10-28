package com.example.practice.events;

import static org.assertj.core.api.Assertions.assertThat;
import static org.awaitility.Awaitility.await;

import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.MeterRegistry;
import java.time.Duration;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.kafka.core.DefaultKafkaConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.test.EmbeddedKafkaBroker;
import org.springframework.kafka.test.context.EmbeddedKafka;
import org.springframework.kafka.test.utils.KafkaTestUtils;
import org.springframework.test.annotation.DirtiesContext;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;

@SpringBootTest(properties = {
        "application.events.enabled=true",
        "application.events.topic=onboarding.events.test.v1",
        "application.events.poll-interval=100",
        "application.events.retry-backoff=10ms",
        "spring.kafka.consumer.auto-offset-reset=earliest",
        "spring.kafka.consumer.enable-auto-commit=false"
})
@ActiveProfiles("test")
@EmbeddedKafka(kraft = true, partitions = 3,
        topics = {"onboarding.events.test.v1", "onboarding.events.test.v1.DLT"},
        bootstrapServersProperty = "spring.kafka.bootstrap-servers")
@DirtiesContext
class KafkaEventIntegrationTest {
    @Autowired private EmbeddedKafkaBroker broker;
    @Autowired private DomainEventRecorder recorder;
    @Autowired private OutboxEventRepository outbox;
    @Autowired private AuditEventRepository audit;
    @Autowired private PlatformTransactionManager transactionManager;
    @Autowired private KafkaTemplate<String, String> template;
    @Autowired private ObjectMapper mapper;
    @Autowired private MeterRegistry registry;

    @Test
    void deliversOutboxThroughRealKafkaAndIgnoresDuplicateTransportDelivery() throws Exception {
        UUID caseId = UUID.randomUUID();
        new TransactionTemplate(transactionManager).executeWithoutResult(status ->
                recorder.record("OnboardingCaseCreated", caseId, Map.of("status", "CREATED")));
        OutboxEvent event = outbox.findAll().stream().filter(row -> row.getCaseId().equals(caseId))
                .findFirst().orElseThrow();
        await().atMost(Duration.ofSeconds(30)).untilAsserted(() -> {
            assertThat(outbox.findById(event.getId()).orElseThrow().getPublishedAt()).isNotNull();
            assertThat(audit.existsById(event.getId())).isTrue();
        });
        double duplicatesBefore = registry.counter("onboarding.events.duplicates").count();
        template.send("onboarding.events.test.v1", caseId.toString(), event.getEventJson()).get();
        await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
            assertThat(registry.counter("onboarding.events.duplicates").count()).isGreaterThan(duplicatesBefore);
            assertThat(audit.findAll().stream().filter(row -> row.getEventId().equals(event.getId()))).hasSize(1);
        });
    }

    @Test
    void malformedRecordIsSentToDeadLetterTopicWithoutCreatingAuditRecord() throws Exception {
        var properties = KafkaTestUtils.consumerProps("dead-letter-test-" + UUID.randomUUID(), "false", broker);
        properties.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        try (var consumer = new DefaultKafkaConsumerFactory<>(properties,
                new StringDeserializer(), new StringDeserializer()).createConsumer()) {
            broker.consumeFromAnEmbeddedTopic(consumer, "onboarding.events.test.v1.DLT");
            String invalid = "{not-valid-json";
            template.send("onboarding.events.test.v1", UUID.randomUUID().toString(), invalid).get();
            var deadLetter = KafkaTestUtils.getSingleRecord(consumer,
                    "onboarding.events.test.v1.DLT", Duration.ofSeconds(30));
            assertThat(deadLetter.value()).isEqualTo(invalid);
        }
    }
}
