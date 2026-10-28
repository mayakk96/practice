package com.example.practice.knowledge;

/** Converts text into a fixed-length vector; implementations must use the same space for queries and documents. */
public interface EmbeddingModel {
    double[] embed(String text);

    String name();
}
