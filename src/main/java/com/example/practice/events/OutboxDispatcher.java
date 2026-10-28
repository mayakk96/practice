package com.example.practice.events;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(prefix = "application.events", name = "enabled", havingValue = "true")
public class OutboxDispatcher {
    private final OutboxDeliveryService deliveryService;
    private final EventsProperties properties;

    public OutboxDispatcher(OutboxDeliveryService deliveryService, EventsProperties properties) {
        this.deliveryService = deliveryService;
        this.properties = properties;
    }

    @Scheduled(fixedDelayString = "${application.events.poll-interval:2000}")
    public void dispatch() {
        for (int i = 0; i < properties.getBatchSize() && !Thread.currentThread().isInterrupted(); i++) {
            if (!deliveryService.deliverNext()) {
                break;
            }
        }
    }
}
