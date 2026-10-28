package com.example.practice.knowledge;

import java.util.List;
import java.util.stream.Collectors;

import jakarta.validation.ConstraintViolationException;
import jakarta.validation.Validator;
import org.springframework.stereotype.Service;

@Service
public class KnowledgeService {
    private static final int CONTEXT_CHARACTERS = 6000;
    private final PolicyVectorIndex index;
    private final EmbeddingModel embeddingModel;
    private final PolicyAnswerModel answerModel;
    private final Validator validator;

    public KnowledgeService(PolicyVectorIndex index, EmbeddingModel embeddingModel, PolicyAnswerModel answerModel,
            Validator validator) {
        this.index = index;
        this.embeddingModel = embeddingModel;
        this.answerModel = answerModel;
        this.validator = validator;
    }

    public KnowledgeResponse search(KnowledgeRequest request) {
        var errors = validator.validate(request);
        if (!errors.isEmpty()) {
            throw new ConstraintViolationException(errors);
        }
        List<PolicyVectorIndex.Match> matches = index.search(request.query(), request.limit());
        List<PolicyChunk> evidence = boundedEvidence(matches);
        if (evidence.isEmpty()) {
            return new KnowledgeResponse("The bundled fictional policies do not contain an answer to this question.",
                    false, embeddingModel.name(), "not-called-no-evidence", List.of());
        }
        String context = evidence.stream().map(chunk -> "[" + chunk.id() + "] " + chunk.text()).collect(Collectors.joining("\n\n"));
        String answer = answerModel.answer(request.query(), context, evidence);
        List<KnowledgeResponse.Citation> citations = matches.stream().filter(match -> evidence.contains(match.chunk()))
                .map(match -> new KnowledgeResponse.Citation(match.chunk().id(), match.chunk().source(), match.chunk().text(), match.score()))
                .toList();
        return new KnowledgeResponse(answer, true, embeddingModel.name(), answerModel.name(), citations);
    }

    private List<PolicyChunk> boundedEvidence(List<PolicyVectorIndex.Match> matches) {
        java.util.ArrayList<PolicyChunk> evidence = new java.util.ArrayList<>();
        int characters = 0;
        for (PolicyVectorIndex.Match match : matches) {
            int nextLength = match.chunk().text().length() + match.chunk().id().length() + 8;
            if (characters + nextLength > CONTEXT_CHARACTERS) {
                break;
            }
            evidence.add(match.chunk());
            characters += nextLength;
        }
        return List.copyOf(evidence);
    }
}
