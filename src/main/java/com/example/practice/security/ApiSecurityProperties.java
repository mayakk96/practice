package com.example.practice.security;

import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties("application.security")
public record ApiSecurityProperties(@NotBlank String username, @NotBlank String password,
                                    String readOnlyUsername, String readOnlyPassword) {
}
