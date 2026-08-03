package io.setugateway;

import static com.github.tomakehurst.wiremock.client.WireMock.aResponse;
import static com.github.tomakehurst.wiremock.client.WireMock.equalTo;
import static com.github.tomakehurst.wiremock.client.WireMock.get;
import static com.github.tomakehurst.wiremock.client.WireMock.post;
import static com.github.tomakehurst.wiremock.client.WireMock.postRequestedFor;
import static com.github.tomakehurst.wiremock.client.WireMock.urlEqualTo;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

import com.fasterxml.jackson.databind.JsonNode;
import com.github.tomakehurst.wiremock.WireMockServer;
import java.util.Collections;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;

class SetuClientTest {
    private WireMockServer wireMock;

    @BeforeEach
    void setUp() {
        wireMock = new WireMockServer(0);
        wireMock.start();
    }

    @AfterEach
    void tearDown() {
        wireMock.stop();
    }

    private SetuClient client(String apiKey) {
        return new SetuClient.Builder().baseUrl(wireMock.baseUrl()).apiKey(apiKey).build();
    }

    @Test
    void chatCompletionsCreateSendsExpectedRequestAndParsesResponse() {
        // Instance methods on `wireMock`, not the static WireMock.stubFor/verify
        // convenience methods - those target a default client bound to port 8080,
        // not this test's dynamically-allocated port, and fail confusingly
        // (a 404 from the *admin* API, not the stubbed endpoint) if used here.
        wireMock.stubFor(post(urlEqualTo("/v1/chat/completions"))
                .willReturn(aResponse()
                        .withHeader("Content-Type", "application/json")
                        .withBody("{\"id\":\"chatcmpl-1\",\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"hi back\"}}]}")));

        SetuClient client = client("sk_setu_test");
        JsonNode resp = client.chat().completions().create(
                new ChatCompletionRequest("gpt-4o", List.of(new Message("user", "hi"))));

        assertEquals("chatcmpl-1", resp.get("id").asText());
        wireMock.verify(postRequestedFor(urlEqualTo("/v1/chat/completions"))
                .withHeader("Authorization", equalTo("Bearer sk_setu_test")));
    }

    @Test
    void requestFailureThrowsSetuApiException() {
        wireMock.stubFor(get(urlEqualTo("/v1/models"))
                .willReturn(aResponse().withStatus(401).withBody("{\"detail\":\"invalid key\"}")));

        SetuClient client = client(null);
        SetuApiException ex = assertThrows(SetuApiException.class, () -> client.models().list());
        assertEquals(401, ex.getStatusCode());
        assertEquals("invalid key", ex.getBody());
    }

    @Test
    void connectionFailureThrowsSetuConnectionException() {
        SetuClient client = new SetuClient.Builder().baseUrl("http://127.0.0.1:1").build();
        assertThrows(SetuConnectionException.class, () -> client.models().list());
    }

    @Test
    void embeddingsCreateSendsExpectedRequest() {
        wireMock.stubFor(post(urlEqualTo("/v1/embeddings"))
                .willReturn(aResponse().withBody("{\"data\":[{\"embedding\":[0.1,0.2]}]}")));

        SetuClient client = client(null);
        JsonNode resp = client.embeddings().create(new EmbeddingRequest("text-embedding-3-small", "hello"));
        assertTrue(resp.has("data"));
    }

    /** Only meaningful when a real gateway is reachable at the default base URL -
     * a connection failure here is treated as "can't verify in this environment",
     * not a test failure. */
    @Test
    void liveGatewaySmoke() {
        SetuClient client = new SetuClient.Builder().build();
        try {
            JsonNode resp = client.chat().completions().create(
                    new ChatCompletionRequest("gpt-4o",
                            Collections.singletonList(new Message("user", "Say 'sdk-java works' and nothing else."))));
            assertTrue(resp.has("id"), "expected a response with an id field, got " + resp);
        } catch (SetuConnectionException e) {
            System.err.println("no live gateway reachable at default base URL, skipping assertion: " + e.getMessage());
        }
    }
}
