package com.example.practice.knowledge;

import java.util.Arrays;
import java.util.Locale;
import java.util.Set;
import java.util.regex.Pattern;

import org.springframework.stereotype.Component;

/** An offline educational embedding: normalized signed feature hashing, not a pretrained semantic model. */
@Component
public class HashingEmbeddingModel implements EmbeddingModel {
    private static final int DIMENSIONS = 512;
    private static final Pattern WORD = Pattern.compile("[a-z][a-z0-9_]+", Pattern.CASE_INSENSITIVE);
    private static final Set<String> STOP_WORDS = Set.of("the", "and", "for", "with", "that", "this", "what", "which",
            "how", "are", "can", "does", "have", "from", "into", "before", "after", "should", "must", "will", "only");

    @Override
    public double[] embed(String text) {
        double[] vector = new double[DIMENSIONS];
        WORD.matcher(text.toLowerCase(Locale.ROOT)).results().map(match -> match.group()).filter(token -> !STOP_WORDS.contains(token))
                .forEach(token -> {
                    int hash = token.hashCode();
                    vector[Math.floorMod(hash, DIMENSIONS)] += ((hash >>> 16) & 1) == 0 ? 1 : -1;
                });
        double magnitude = Math.sqrt(Arrays.stream(vector).map(value -> value * value).sum());
        if (magnitude > 0) {
            for (int index = 0; index < vector.length; index++) {
                vector[index] /= magnitude;
            }
        }
        return vector;
    }

    @Override
    public String name() {
        return "signed-feature-hash-512";
    }
}
