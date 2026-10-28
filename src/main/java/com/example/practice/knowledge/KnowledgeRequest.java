package com.example.practice.knowledge;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record KnowledgeRequest(@NotBlank @Size(max = 500) String query, @Min(1) @Max(5) Integer topK) {
    public int limit() {
        return topK == null ? 3 : topK;
    }
}
