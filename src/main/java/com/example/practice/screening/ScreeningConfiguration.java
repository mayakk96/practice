package com.example.practice.screening;

import java.net.http.HttpClient;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods = false)
@EnableConfigurationProperties(ScreeningProperties.class)
public class ScreeningConfiguration {

    @Bean
    @ConditionalOnProperty(prefix = "application.screening", name = "mode", havingValue = "stub", matchIfMissing = true)
    RiskScreeningClient stubRiskScreeningClient() {
        return caseId -> new ScreeningResult(RiskLevel.LOW, "stub-" + caseId);
    }

    @Bean
    @ConditionalOnProperty(prefix = "application.screening", name = "mode", havingValue = "http")
    RiskScreeningClient httpRiskScreeningClient(RestClient.Builder builder, ScreeningProperties properties) {
        HttpClient http = HttpClient.newBuilder()
                .connectTimeout(properties.getConnectTimeout())
                .followRedirects(HttpClient.Redirect.NEVER)
                .build();
        JdkClientHttpRequestFactory requestFactory = new JdkClientHttpRequestFactory(http);
        requestFactory.setReadTimeout(properties.getReadTimeout());
        RestClient client = builder.clone()
                .baseUrl(properties.getBaseUrl().toString())
                .requestFactory(requestFactory)
                .requestInterceptor((request, body, execution) -> {
                    // Interceptors receive Jackson's serialized bytes. Supplying their exact length
                    // avoids chunked requests, which the bounded local provider does not support.
                    request.getHeaders().setContentLength(body.length);
                    return execution.execute(request, body);
                })
                .build();
        return new HttpRiskScreeningClient(client, properties);
    }
}
