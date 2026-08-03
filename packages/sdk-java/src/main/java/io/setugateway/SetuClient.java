package io.setugateway;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * Official Java client for Setu Gateway's OpenAI-compatible API.
 *
 * <pre>{@code
 * SetuClient client = new SetuClient.Builder().apiKey("sk_setu_...").build();
 * JsonNode resp = client.chat().completions().create(
 *     new ChatCompletionRequest("gpt-4o", List.of(new Message("user", "hi"))));
 * }</pre>
 *
 * Streaming ({@code stream=true}) isn't supported by this SDK yet - use the Python
 * or TypeScript SDK if you need server-sent-event streaming today.
 */
public class SetuClient {
    private static final String DEFAULT_BASE_URL = "http://localhost:8000";

    private final HttpClient http;
    private final ObjectMapper mapper = new ObjectMapper();
    private final String baseUrl;
    private final String apiKey;

    private SetuClient(String baseUrl, String apiKey, Duration timeout) {
        this.baseUrl = baseUrl;
        this.apiKey = apiKey;
        // java.net.http.HttpClient defaults to preferring HTTP/2, which over plain
        // HTTP means attempting an "h2c" upgrade handshake first. The gateway
        // (uvicorn, HTTP/1.1 only) doesn't understand that handshake and responds
        // with a raw "Invalid HTTP request received" instead of a normal HTTP
        // error - forcing HTTP/1.1 avoids the upgrade attempt entirely.
        this.http = HttpClient.newBuilder().connectTimeout(timeout).version(HttpClient.Version.HTTP_1_1).build();
    }

    public static class Builder {
        private String baseUrl = System.getenv().getOrDefault("SETU_BASE_URL", DEFAULT_BASE_URL);
        private String apiKey = System.getenv("SETU_API_KEY");
        private Duration timeout = Duration.ofSeconds(60);

        public Builder baseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
            return this;
        }

        public Builder apiKey(String apiKey) {
            this.apiKey = apiKey;
            return this;
        }

        public Builder timeout(Duration timeout) {
            this.timeout = timeout;
            return this;
        }

        public SetuClient build() {
            return new SetuClient(baseUrl, apiKey, timeout);
        }
    }

    private JsonNode request(String method, String path, Object body) {
        try {
            HttpRequest.Builder builder = HttpRequest.newBuilder()
                    .uri(URI.create(baseUrl + path))
                    .header("Content-Type", "application/json");
            if (apiKey != null && !apiKey.isEmpty()) {
                builder.header("Authorization", "Bearer " + apiKey);
            }

            HttpRequest.BodyPublisher publisher = body == null
                    ? HttpRequest.BodyPublishers.noBody()
                    : HttpRequest.BodyPublishers.ofString(mapper.writeValueAsString(body));
            builder.method(method, publisher);

            HttpResponse<String> response = http.send(builder.build(), HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() >= 300) {
                String message = response.body();
                try {
                    JsonNode errorBody = mapper.readTree(response.body());
                    if (errorBody.has("detail")) {
                        message = errorBody.get("detail").asText();
                    }
                } catch (IOException ignored) {
                    // response body wasn't JSON - fall back to the raw text already assigned above.
                }
                throw new SetuApiException(response.statusCode(), message);
            }
            return mapper.readTree(response.body());
        } catch (IOException e) {
            throw new SetuConnectionException(baseUrl, e);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new SetuConnectionException(baseUrl, e);
        }
    }

    public ChatNamespace chat() {
        return new ChatNamespace();
    }

    public EmbeddingsNamespace embeddings() {
        return new EmbeddingsNamespace();
    }

    public ModelsNamespace models() {
        return new ModelsNamespace();
    }

    public class ChatNamespace {
        public ChatCompletionsNamespace completions() {
            return new ChatCompletionsNamespace();
        }
    }

    public class ChatCompletionsNamespace {
        public JsonNode create(ChatCompletionRequest req) {
            return request("POST", "/v1/chat/completions", req);
        }
    }

    public class EmbeddingsNamespace {
        public JsonNode create(EmbeddingRequest req) {
            return request("POST", "/v1/embeddings", req);
        }
    }

    public class ModelsNamespace {
        public JsonNode list() {
            return request("GET", "/v1/models", null);
        }
    }
}
