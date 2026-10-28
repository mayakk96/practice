package com.example.practice.onboarding.api;

import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;

public record CreateCaseRequest(
        @NotBlank @Size(max = 80) String firstName,
        @NotBlank @Size(max = 80) String lastName,
        @NotBlank @Email @Size(max = 254)
        @Pattern(regexp = "(?i)^[^@\\s]+@(?:example\\.com|[a-z0-9.-]+\\.test)$",
                message = "must use example.com or a .test domain for fictional data") String email,
        @Pattern(regexp = "[A-Z][A-Z0-9_]{1,39}",
                message = "must be an uppercase team identifier of 2 to 40 characters") String assignedTeam) {
}
