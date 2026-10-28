package com.example.practice.events;

import java.time.Duration;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.clients.admin.NewTopic;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.ConcurrentKafkaListenerContainerFactory;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.ConsumerFactory;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.ContainerProperties;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.util.backoff.FixedBackOff;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(prefix = "application.events", name = "enabled", havingValue = "true")
public class OnboardingKafkaConfiguration {
    @Bean
    public NewTopic onboardingEventsTopic(EventsProperties properties) {
        return TopicBuilder.name(properties.getTopic()).partitions(3).replicas(1).build();
    }

    @Bean
    public NewTopic onboardingEventsDeadLetterTopic(EventsProperties properties) {
        return TopicBuilder.name(properties.getTopic() + ".DLT").partitions(3).replicas(1).build();
    }

    @Bean
    public ConcurrentKafkaListenerContainerFactory<String, String> onboardingKafkaListenerContainerFactory(
            ConsumerFactory<String, String> consumerFactory, KafkaTemplate<String, String> template,
            EventsProperties properties) {
        var factory = new ConcurrentKafkaListenerContainerFactory<String, String>();
        factory.setConsumerFactory(consumerFactory);
        factory.getContainerProperties().setAckMode(ContainerProperties.AckMode.RECORD);
        var recoverer = new DeadLetterPublishingRecoverer(template,
                (record, exception) -> new TopicPartition(properties.getTopic() + ".DLT", record.partition()));
        recoverer.setFailIfSendResultIsError(true);
        recoverer.setWaitForSendResultTimeout(Duration.ofSeconds(12));
        var errorHandler = new DefaultErrorHandler(recoverer,
                new FixedBackOff(properties.getRetryBackoff().toMillis(), 2));
        errorHandler.addNotRetryableExceptions(InvalidDomainEventException.class);
        factory.setCommonErrorHandler(errorHandler);
        return factory;
    }
}
