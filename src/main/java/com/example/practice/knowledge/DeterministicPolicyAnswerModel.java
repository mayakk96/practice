package com.example.practice.knowledge;

import java.util.List;
import java.util.stream.Collectors;

/** A deterministic, extractive test/demo model. It makes no remote call and is deliberately not presented as an LLM. */
public class DeterministicPolicyAnswerModel implements PolicyAnswerModel {
    @Override
    public String answer(String question, String context, List<PolicyChunk> evidence) {
        return evidence.stream().map(chunk -> "[" + chunk.id() + "] " + chunk.text()).collect(Collectors.joining("\n\n"));
    }

    @Override
    public String name() {
        return "deterministic-extractive-demo";
    }
}
