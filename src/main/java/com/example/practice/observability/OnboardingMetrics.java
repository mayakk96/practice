package com.example.practice.observability;

import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.repository.OnboardingCaseRepository;
import com.example.practice.events.OutboxEventRepository;
import io.micrometer.core.instrument.MeterRegistry;
import org.springframework.stereotype.Component;

@Component
public class OnboardingMetrics {
    public OnboardingMetrics(OnboardingCaseRepository cases, OutboxEventRepository outbox, MeterRegistry registry) {
        // Seven bounded status labels; never use applicant IDs or free-form values as metric tags.
        for (CaseStatus status : CaseStatus.values()) {
            registry.gauge("onboarding.cases", java.util.List.of(io.micrometer.core.instrument.Tag.of("status", status.name())),
                    cases, repository -> repository.countByStatus(status));
        }
        registry.gauge("onboarding.events.pending", outbox, OutboxEventRepository::countByPublishedAtIsNull);
    }
}
