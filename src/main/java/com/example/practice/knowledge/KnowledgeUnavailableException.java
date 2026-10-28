package com.example.practice.knowledge;

public class KnowledgeUnavailableException extends RuntimeException {
    public KnowledgeUnavailableException() {
        super("The configured policy answer model is unavailable.");
    }
}
