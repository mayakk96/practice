package com.example.practice.security;

import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.ArrayList;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.core.userdetails.User;
import org.springframework.security.core.userdetails.UserDetails;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.security.core.userdetails.UsernameNotFoundException;
import org.springframework.security.crypto.factory.PasswordEncoderFactories;
import org.springframework.security.provisioning.InMemoryUserDetailsManager;
import org.springframework.security.web.SecurityFilterChain;

@Configuration(proxyBeanMethods = false)
public class SecurityConfiguration {

    @Configuration(proxyBeanMethods = false)
    @ConditionalOnProperty(name = "application.security.enabled", havingValue = "true", matchIfMissing = true)
    @EnableConfigurationProperties(ApiSecurityProperties.class)
    static class AuthenticatedApi {
        @Bean
        UserDetailsService users(ApiSecurityProperties properties) {
            var encoder = PasswordEncoderFactories.createDelegatingPasswordEncoder();
            var users = new ArrayList<UserDetails>();
            users.add(User.withUsername(properties.username()).password(encoder.encode(properties.password()))
                    .roles("OPERATOR", "READER").build());
            boolean hasReaderName = properties.readOnlyUsername() != null && !properties.readOnlyUsername().isBlank();
            boolean hasReaderPassword = properties.readOnlyPassword() != null && !properties.readOnlyPassword().isBlank();
            if (hasReaderName != hasReaderPassword) {
                throw new IllegalStateException("Configure both read-only username and password, or neither.");
            }
            if (hasReaderName) {
                if (properties.username().equals(properties.readOnlyUsername())) {
                    throw new IllegalStateException("Operator and read-only usernames must differ.");
                }
                users.add(User.withUsername(properties.readOnlyUsername())
                        .password(encoder.encode(properties.readOnlyPassword())).roles("READER").build());
            }
            return new InMemoryUserDetailsManager(users);
        }

        @Bean
        SecurityFilterChain authenticatedChain(HttpSecurity http, ObjectMapper mapper) throws Exception {
            // Stateless HTTP Basic is a local development mechanism; no cookie-based sessions.
            return http.csrf(csrf -> csrf.disable())
                    .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                    .authorizeHttpRequests(auth -> auth
                            .requestMatchers("/actuator/health", "/actuator/health/**", "/actuator/info").permitAll()
                            .requestMatchers("/actuator/**").hasRole("OPERATOR")
                            .requestMatchers("/mcp", "/mcp/**").hasRole("READER")
                            .requestMatchers(HttpMethod.GET, "/api/**").hasRole("READER")
                            .requestMatchers(HttpMethod.POST, "/api/knowledge/search").hasRole("READER")
                            .requestMatchers("/api/onboarding/**").hasRole("OPERATOR")
                            .anyRequest().authenticated())
                    .httpBasic(basic -> basic.authenticationEntryPoint((request, response, failure) -> {
                        response.setHeader("WWW-Authenticate", "Basic realm=\"onboarding\"");
                        writeProblem(mapper, response, HttpStatus.UNAUTHORIZED, "Valid API credentials are required.");
                    }))
                    .exceptionHandling(errors -> errors.accessDeniedHandler((request, response, failure) ->
                            writeProblem(mapper, response, HttpStatus.FORBIDDEN, "This account cannot perform that operation.")))
                    .build();
        }
    }

    @Configuration(proxyBeanMethods = false)
    @ConditionalOnProperty(name = "application.security.enabled", havingValue = "false")
    static class LocalDemoApi {
        @Bean
        UserDetailsService noGeneratedCredentials() {
            return username -> { throw new UsernameNotFoundException("Authentication disabled for this profile."); };
        }

        @Bean
        SecurityFilterChain demoChain(HttpSecurity http) throws Exception {
            return http.csrf(csrf -> csrf.disable())
                    .sessionManagement(session -> session.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
                    .authorizeHttpRequests(auth -> auth.anyRequest().permitAll()).build();
        }
    }

    private static void writeProblem(ObjectMapper mapper, HttpServletResponse response,
                                     HttpStatus status, String detail) throws IOException {
        response.setStatus(status.value());
        response.setContentType(MediaType.APPLICATION_PROBLEM_JSON_VALUE);
        var problem = ProblemDetail.forStatusAndDetail(status, detail);
        problem.setProperty("requestId", org.slf4j.MDC.get("requestId"));
        mapper.writeValue(response.getOutputStream(), problem);
    }
}
