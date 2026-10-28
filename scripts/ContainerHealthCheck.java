import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/** Checks application readiness without adding curl or a shell to the image. */
public final class ContainerHealthCheck {
    public static void main(String[] args) throws Exception {
        HttpClient client = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
        HttpRequest request = HttpRequest.newBuilder(URI.create("http://127.0.0.1:8080/actuator/health"))
                .timeout(Duration.ofSeconds(3)).GET().build();
        HttpResponse<String> response = client.send(request, HttpResponse.BodyHandlers.ofString());
        if (response.statusCode() != 200 || !response.body().contains("\"UP\"")) {
            System.exit(1);
        }
    }
}
