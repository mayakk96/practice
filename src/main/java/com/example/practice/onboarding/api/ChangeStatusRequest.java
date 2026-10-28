package com.example.practice.onboarding.api;

import com.example.practice.onboarding.model.CaseStatus;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;

public record ChangeStatusRequest(@NotNull CaseStatus status, @NotBlank @Size(max = 500) String reason) {
}
