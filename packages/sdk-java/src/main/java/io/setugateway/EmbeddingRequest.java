package io.setugateway;

/** Mirrors POST /v1/embeddings's request body. `input` is an Object because it may
 * be a single String or a List&lt;String&gt;, matching the OpenAI-compatible API. */
public class EmbeddingRequest {
    public String model;
    public Object input;

    public EmbeddingRequest(String model, Object input) {
        this.model = model;
        this.input = input;
    }
}
