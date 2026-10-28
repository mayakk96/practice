package com.example.practice.screening;

import com.sun.net.httpserver.HttpServer;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.InetSocketAddress;
import java.net.ServerSocket;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.UUID;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

/** Real loopback sockets prove the configured HTTP timeout, rather than mocking a timeout exception. */
class ScreeningHttpTimeoutTest {

    @Test
    void sendsFixedLengthJsonToAProviderThatDoesNotAcceptChunkedRequests() throws IOException {
        UUID caseId = UUID.randomUUID();
        AtomicReference<ReceivedRequest> received = new AtomicReference<>();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/screenings", exchange -> {
            String length = exchange.getRequestHeaders().getFirst("Content-Length");
            if (length == null) {
                exchange.sendResponseHeaders(411, -1);
                exchange.close();
                return;
            }
            byte[] body = exchange.getRequestBody().readAllBytes();
            received.set(new ReceivedRequest(length, exchange.getRequestHeaders().getFirst("Transfer-Encoding"),
                    exchange.getRequestHeaders().getFirst("Idempotency-Key"), body));
            byte[] response = "{\"riskLevel\":\"LOW\",\"providerReference\":\"fixed-length-provider\"}"
                    .getBytes(StandardCharsets.UTF_8);
            exchange.getResponseHeaders().set("Content-Type", "application/json");
            exchange.sendResponseHeaders(200, response.length);
            exchange.getResponseBody().write(response);
            exchange.close();
        });
        server.start();
        try {
            RiskScreeningClient client = new ScreeningConfiguration()
                    .httpRiskScreeningClient(RestClient.builder(), properties(server.getAddress().getPort()));

            assertThat(client.screen(caseId)).isEqualTo(new ScreeningResult(RiskLevel.LOW, "fixed-length-provider"));
            ReceivedRequest wire = received.get();
            assertThat(wire).isNotNull();
            assertThat(wire.contentLength()).isEqualTo(Integer.toString(wire.body().length));
            assertThat(wire.transferEncoding()).isNull();
            assertThat(wire.idempotencyKey()).isEqualTo(caseId.toString());
            var json = new ObjectMapper().readTree(wire.body());
            assertThat(json.size()).isEqualTo(1);
            assertThat(json.path("caseId").asText()).isEqualTo(caseId.toString());
        } finally {
            server.stop(0);
        }
    }

    @Test
    void abandonsASlowProviderAndBoundsTheTotalRetryTime() throws IOException {
        AtomicInteger calls = new AtomicInteger();
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        try (var executor = Executors.newVirtualThreadPerTaskExecutor()) {
            server.setExecutor(executor);
            server.createContext("/screenings", exchange -> {
                calls.incrementAndGet();
                exchange.getRequestBody().readAllBytes();
                try {
                    Thread.sleep(Duration.ofMillis(500));
                    byte[] body = "{\"riskLevel\":\"LOW\",\"providerReference\":\"slow-ref\"}".getBytes();
                    exchange.getResponseHeaders().set("Content-Type", "application/json");
                    exchange.sendResponseHeaders(200, body.length);
                    exchange.getResponseBody().write(body);
                } catch (InterruptedException cancelled) {
                    Thread.currentThread().interrupt();
                } catch (IOException clientTimedOut) {
                    // Expected: the caller has already cancelled this slow response.
                } finally {
                    exchange.close();
                }
            });
            server.start();
            ScreeningProperties properties = properties(server.getAddress().getPort());
            properties.setReadTimeout(Duration.ofMillis(100));
            properties.setMaxAttempts(2);
            RiskScreeningClient client = new ScreeningConfiguration()
                    .httpRiskScreeningClient(RestClient.builder(), properties);

            long started = System.nanoTime();
            assertThatThrownBy(() -> client.screen(UUID.randomUUID()))
                    .isInstanceOf(ScreeningUnavailableException.class);
            Duration elapsed = Duration.ofNanos(System.nanoTime() - started);

            assertThat(elapsed).isLessThan(Duration.ofSeconds(3));
            assertThat(calls.get()).isEqualTo(2);
        } finally {
            server.stop(0);
        }
    }

    @Test
    void translatesConnectionRefusalAndStopsRetrying() throws IOException {
        int port;
        try (ServerSocket unused = new ServerSocket(0)) {
            port = unused.getLocalPort();
        }
        ScreeningProperties properties = properties(port);
        properties.setMaxAttempts(2);
        RiskScreeningClient client = new ScreeningConfiguration()
                .httpRiskScreeningClient(RestClient.builder(), properties);

        assertThatThrownBy(() -> client.screen(UUID.randomUUID()))
                .isInstanceOf(ScreeningUnavailableException.class).hasNoCause();
    }

    private ScreeningProperties properties(int port) {
        ScreeningProperties properties = new ScreeningProperties();
        properties.setMode("http");
        properties.setBaseUrl(java.net.URI.create("http://127.0.0.1:" + port));
        properties.setConnectTimeout(Duration.ofMillis(200));
        properties.setBackoff(Duration.ZERO);
        return properties;
    }

    private record ReceivedRequest(String contentLength, String transferEncoding, String idempotencyKey, byte[] body) {
    }
}
