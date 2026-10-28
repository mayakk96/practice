package com.example.practice.onboarding.api;

import com.example.practice.onboarding.model.DocumentType;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record SubmitDocumentRequest(
        @NotNull DocumentType documentType,
        @NotBlank @Size(max = 100)
        @Pattern(regexp = "[A-Za-z0-9._:-]+", message = "must be a fictional reference identifier") String reference) {
}
