package com.example.practice.knowledge;

import java.net.http.HttpClient;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.HttpHeaders;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(KnowledgeProperties.class)
public class KnowledgeConfiguration {
    @Bean
    PolicyAnswerModel policyAnswerModel(KnowledgeProperties properties) {
        if (properties.mode().equals("deterministic")) {
            return new DeterministicPolicyAnswerModel();
        }
        String scheme = properties.baseUrl().getScheme();
        if ((!"http".equals(scheme) && !"https".equals(scheme)) || properties.baseUrl().getUserInfo() != null
                || properties.baseUrl().getHost() == null || properties.baseUrl().getQuery() != null) {
            throw new IllegalArgumentException("Knowledge base URL must be an HTTP(S) URL without credentials or query");
        }
        if (properties.apiKey() != null && !properties.apiKey().isBlank() && !"https".equals(scheme)
                && !isLoopback(properties.baseUrl().getHost())) {
            throw new IllegalArgumentException("Knowledge credentials require HTTPS except for a loopback development model");
        }
        HttpClient httpClient = HttpClient.newBuilder().connectTimeout(properties.connectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER).build();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
        factory.setReadTimeout(properties.readTimeout());
        RestClient.Builder client = RestClient.builder().baseUrl(properties.baseUrl().toString()).requestFactory(factory);
        if (properties.apiKey() != null && !properties.apiKey().isBlank()) {
            client.defaultHeader(HttpHeaders.AUTHORIZATION, "Bearer " + properties.apiKey());
        }
        return new HttpPolicyAnswerModel(client.build(), properties.model());
    }

    private boolean isLoopback(String host) {
        return host.equals("localhost") || host.equals("127.0.0.1") || host.equals("[::1]") || host.equals("::1");
    }
}
