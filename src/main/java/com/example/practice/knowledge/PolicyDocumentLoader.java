package com.example.practice.knowledge;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Comparator;
import java.util.List;

import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.stereotype.Component;

@Component
public class PolicyDocumentLoader {
    private static final int CHUNK_WORDS = 80;
    private static final int OVERLAP_WORDS = 15;

    public List<PolicyChunk> load() {
        try {
            Resource[] documents = new PathMatchingResourcePatternResolver().getResources("classpath:knowledge/*.txt");
            Arrays.sort(documents, Comparator.comparing(resource -> String.valueOf(resource.getFilename())));
            List<PolicyChunk> chunks = new ArrayList<>();
            for (Resource document : documents) {
                String content = document.getContentAsString(StandardCharsets.UTF_8);
                chunks.addAll(chunk(document.getFilename(), content));
            }
            if (chunks.isEmpty()) {
                throw new IllegalStateException("No bundled fictional policy documents were found");
            }
            return List.copyOf(chunks);
        } catch (IOException exception) {
            throw new IllegalStateException("Unable to load bundled fictional policy documents", exception);
        }
    }

    static List<PolicyChunk> chunk(String source, String content) {
        List<PolicyChunk> chunks = new ArrayList<>();
        String normalized = content.strip();
        if (normalized.isEmpty()) {
            return chunks;
        }
        String[] words = normalized.split("\\s+");
        for (int start = 0, part = 1; start < words.length; start += CHUNK_WORDS - OVERLAP_WORDS, part++) {
            int end = Math.min(start + CHUNK_WORDS, words.length);
            chunks.add(new PolicyChunk(source + "#" + part, source, String.join(" ", Arrays.copyOfRange(words, start, end))));
            if (end == words.length) {
                break;
            }
        }
        return chunks;
    }
}
