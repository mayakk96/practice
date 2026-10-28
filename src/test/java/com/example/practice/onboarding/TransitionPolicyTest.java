package com.example.practice.onboarding;

import com.example.practice.onboarding.model.CaseStatus;
import com.example.practice.onboarding.service.BusinessConflictException;
import com.example.practice.onboarding.service.TransitionPolicy;
import java.util.stream.Stream;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.Arguments;
import org.junit.jupiter.params.provider.MethodSource;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

class TransitionPolicyTest {

    private final TransitionPolicy policy = new TransitionPolicy();

    @ParameterizedTest(name = "{0} can transition to {1}")
    @MethodSource("allowedTransitions")
    void supportsTheDocumentedWorkflow(CaseStatus current, CaseStatus next) {
        assertThat(policy.canTransition(current, next)).isTrue();
        assertThatCode(() -> policy.validate(current, next)).doesNotThrowAnyException();
    }

    static Stream<Arguments> allowedTransitions() {
        return Stream.of(
                Arguments.of(CaseStatus.CREATED, CaseStatus.DOCUMENTS_PENDING),
                Arguments.of(CaseStatus.DOCUMENTS_PENDING, CaseStatus.UNDER_REVIEW),
                Arguments.of(CaseStatus.UNDER_REVIEW, CaseStatus.RISK_REVIEW),
                Arguments.of(CaseStatus.UNDER_REVIEW, CaseStatus.DOCUMENTS_PENDING),
                Arguments.of(CaseStatus.UNDER_REVIEW, CaseStatus.APPROVED),
                Arguments.of(CaseStatus.UNDER_REVIEW, CaseStatus.REJECTED),
                Arguments.of(CaseStatus.RISK_REVIEW, CaseStatus.APPROVED),
                Arguments.of(CaseStatus.RISK_REVIEW, CaseStatus.DOCUMENTS_PENDING),
                Arguments.of(CaseStatus.RISK_REVIEW, CaseStatus.REJECTED),
                Arguments.of(CaseStatus.APPROVED, CaseStatus.COMPLETED));
    }

    @ParameterizedTest(name = "{0} cannot transition to {1}")
    @MethodSource("invalidTransitions")
    void rejectsShortcutsRewindsAndRepeatedTransitions(CaseStatus current, CaseStatus next) {
        assertThat(policy.canTransition(current, next)).isFalse();
        assertThatThrownBy(() -> policy.validate(current, next))
                .isInstanceOf(BusinessConflictException.class);
    }

    static Stream<Arguments> invalidTransitions() {
        return Stream.of(
                Arguments.of(CaseStatus.CREATED, CaseStatus.COMPLETED),
                Arguments.of(CaseStatus.CREATED, CaseStatus.APPROVED),
                Arguments.of(CaseStatus.APPROVED, CaseStatus.CREATED),
                Arguments.of(CaseStatus.APPROVED, CaseStatus.DOCUMENTS_PENDING),
                Arguments.of(CaseStatus.REJECTED, CaseStatus.UNDER_REVIEW),
                Arguments.of(CaseStatus.COMPLETED, CaseStatus.CREATED),
                Arguments.of(CaseStatus.UNDER_REVIEW, CaseStatus.UNDER_REVIEW));
    }

    @Test
    void terminalCasesHaveNoOutgoingTransitions() {
        assertThat(policy.allowedTransitions(CaseStatus.REJECTED)).isEmpty();
        assertThat(policy.allowedTransitions(CaseStatus.COMPLETED)).isEmpty();
    }
}
