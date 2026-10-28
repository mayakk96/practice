package com.example.practice.knowledge;

import java.util.Comparator;
import java.util.List;

import org.springframework.stereotype.Component;

@Component
public class PolicyVectorIndex {
    private final EmbeddingModel embeddingModel;
    private final List<IndexedChunk> chunks;

    public PolicyVectorIndex(PolicyDocumentLoader loader, EmbeddingModel embeddingModel) {
        this.embeddingModel = embeddingModel;
        this.chunks = loader.load().stream().map(chunk -> new IndexedChunk(chunk, embeddingModel.embed(chunk.text()))).toList();
    }

    public List<Match> search(String query, int limit) {
        double[] queryVector = embeddingModel.embed(query);
        return chunks.stream().map(chunk -> new Match(chunk.chunk(), cosine(queryVector, chunk.vector())))
                .filter(match -> match.score() >= 0.12)
                .sorted(Comparator.comparingDouble(Match::score).reversed().thenComparing(match -> match.chunk().id()))
                .limit(limit).toList();
    }

    static double cosine(double[] left, double[] right) {
        if (left.length != right.length) {
            throw new IllegalArgumentException("Embedding dimensions differ");
        }
        double dot = 0;
        double leftMagnitude = 0;
        double rightMagnitude = 0;
        for (int index = 0; index < left.length; index++) {
            dot += left[index] * right[index];
            leftMagnitude += left[index] * left[index];
            rightMagnitude += right[index] * right[index];
        }
        return leftMagnitude == 0 || rightMagnitude == 0 ? 0 : dot / Math.sqrt(leftMagnitude * rightMagnitude);
    }

    private record IndexedChunk(PolicyChunk chunk, double[] vector) {
    }

    public record Match(PolicyChunk chunk, double score) {
    }
}
