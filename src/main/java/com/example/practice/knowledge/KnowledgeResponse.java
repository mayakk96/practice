package com.example.practice.knowledge;

import java.util.List;

public record KnowledgeResponse(String answer, boolean grounded, String embeddingModel, String answerModel,
        List<Citation> citations) {
    public record Citation(String chunkId, String source, String excerpt, double score) {
    }
}
