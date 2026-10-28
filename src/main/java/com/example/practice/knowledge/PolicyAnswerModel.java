package com.example.practice.knowledge;

import java.util.List;

public interface PolicyAnswerModel {
    String answer(String question, String context, List<PolicyChunk> evidence);

    String name();
}
