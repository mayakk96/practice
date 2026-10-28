package com.example.practice.knowledge;

import java.util.List;

import jakarta.validation.Validation;
import jakarta.validation.ValidatorFactory;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

class PolicyRetrievalTest {
    private final EmbeddingModel embedding = new HashingEmbeddingModel();

    @Test
    void ingestsBundledPoliciesAndRetrievesRelevantEvidenceWithVectorSimilarity() {
        PolicyDocumentLoader loader = new PolicyDocumentLoader();
        assertThat(loader.load()).hasSizeGreaterThanOrEqualTo(4);
        PolicyVectorIndex index = new PolicyVectorIndex(loader, embedding);

        List<PolicyVectorIndex.Match> matches = index.search("Which documents are required for approval?", 2);

        assertThat(matches).isNotEmpty().hasSizeLessThanOrEqualTo(2);
        assertThat(matches.getFirst().chunk().source()).isEqualTo("approval-policy.txt");
        assertThat(matches.getFirst().chunk().text()).contains("IDENTITY_PROOF", "ADDRESS_PROOF");
        assertThat(matches.getFirst().score()).isBetween(0.12, 1.0);
    }

    @Test
    void chunksLongDocumentsWithOverlapAndStableSourceIdentifiers() {
        String content = java.util.stream.IntStream.range(0, 170).mapToObj(index -> "word" + index)
                .collect(java.util.stream.Collectors.joining(" "));

        List<PolicyChunk> chunks = PolicyDocumentLoader.chunk("sample.txt", content);

        assertThat(chunks).hasSize(3);
        assertThat(chunks.getFirst().id()).isEqualTo("sample.txt#1");
        assertThat(chunks.getFirst().text()).contains("word79").doesNotContain("word80");
        assertThat(chunks.get(1).text()).startsWith("word65 ");
        assertThat(chunks.get(2).text()).endsWith("word169");
        assertThat(PolicyDocumentLoader.chunk("empty.txt", "  ")).isEmpty();
    }

    @Test
    void embeddingsAreStableNormalizedAndCosineIsZeroForAnEmptyQuery() {
        double[] first = embedding.embed("documents approval approval");
        assertThat(first).hasSize(512).containsExactly(embedding.embed("documents approval approval"));
        assertThat(PolicyVectorIndex.cosine(first, first)).isCloseTo(1.0, org.assertj.core.data.Offset.offset(1e-10));
        assertThat(PolicyVectorIndex.cosine(first, embedding.embed(""))).isZero();
        assertThatThrownBy(() -> PolicyVectorIndex.cosine(new double[1], new double[2]))
                .isInstanceOf(IllegalArgumentException.class);
    }

    @Test
    void constructsBoundedEvidenceAndCallsTheSelectedAnswerModel() {
        PolicyVectorIndex index = mock(PolicyVectorIndex.class);
        PolicyAnswerModel model = mock(PolicyAnswerModel.class);
        PolicyChunk first = new PolicyChunk("policy#1", "policy", "Approval requires two documents.");
        PolicyChunk tooLarge = new PolicyChunk("policy#2", "policy", "x".repeat(7000));
        when(index.search(anyString(), anyInt())).thenReturn(List.of(new PolicyVectorIndex.Match(first, 0.8),
                new PolicyVectorIndex.Match(tooLarge, 0.7)));
        when(model.answer(anyString(), anyString(), any())).thenAnswer(invocation -> {
            assertThat((String) invocation.getArgument(1)).contains("[policy#1]").hasSizeLessThanOrEqualTo(6000);
            assertThat((List<?>) invocation.getArgument(2)).hasSize(1);
            return "Two documents are required [policy#1].";
        });
        when(model.name()).thenReturn("test-model");
        try (ValidatorFactory validators = Validation.buildDefaultValidatorFactory()) {
            KnowledgeService service = new KnowledgeService(index, embedding, model, validators.getValidator());
            KnowledgeResponse response = service.search(new KnowledgeRequest("What approval documents?", 3));
            assertThat(response.grounded()).isTrue();
            assertThat(response.citations()).hasSize(1);
            assertThat(response.answer()).contains("[policy#1]");
            assertThat(response.answerModel()).isEqualTo("test-model");
        }
    }

    @Test
    void retrievalFailureDoesNotCallTheModelOrInventAnAnswer() {
        PolicyVectorIndex index = mock(PolicyVectorIndex.class);
        PolicyAnswerModel model = mock(PolicyAnswerModel.class);
        when(index.search(anyString(), anyInt())).thenReturn(List.of());
        try (ValidatorFactory validators = Validation.buildDefaultValidatorFactory()) {
            KnowledgeService service = new KnowledgeService(index, embedding, model, validators.getValidator());
            KnowledgeResponse response = service.search(new KnowledgeRequest("Unrelated question", null));
            assertThat(response.grounded()).isFalse();
            assertThat(response.citations()).isEmpty();
            assertThat(response.answerModel()).isEqualTo("not-called-no-evidence");
            verifyNoInteractions(model);
        }
    }

    @Test
    void evidenceThatCannotFitTheContextBudgetDoesNotCallTheModel() {
        PolicyVectorIndex index = mock(PolicyVectorIndex.class);
        PolicyAnswerModel model = mock(PolicyAnswerModel.class);
        when(index.search(anyString(), anyInt())).thenReturn(List.of(new PolicyVectorIndex.Match(
                new PolicyChunk("oversized#1", "oversized", "x".repeat(7000)), 0.8)));
        try (ValidatorFactory validators = Validation.buildDefaultValidatorFactory()) {
            KnowledgeService service = new KnowledgeService(index, embedding, model, validators.getValidator());
            assertThat(service.search(new KnowledgeRequest("approval", 3)).grounded()).isFalse();
            verifyNoInteractions(model);
        }
    }

    @Test
    void validatesRequestsForBothHttpAndMcpCallers() {
        try (ValidatorFactory validators = Validation.buildDefaultValidatorFactory()) {
            KnowledgeService service = new KnowledgeService(mock(PolicyVectorIndex.class), embedding,
                    mock(PolicyAnswerModel.class), validators.getValidator());
            for (KnowledgeRequest request : List.of(new KnowledgeRequest(" ", 3),
                    new KnowledgeRequest("x".repeat(501), 3), new KnowledgeRequest("approval", 0),
                    new KnowledgeRequest("approval", 6))) {
                assertThatThrownBy(() -> service.search(request)).isInstanceOf(jakarta.validation.ConstraintViolationException.class);
            }
        }
    }
}
