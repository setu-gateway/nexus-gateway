package io.setugateway;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.annotation.JsonProperty;
import java.util.List;

/** Mirrors POST /v1/chat/completions's request body. Streaming (stream=true) isn't
 * supported by this SDK yet - construct without it for a single complete response. */
@JsonInclude(JsonInclude.Include.NON_NULL)
public class ChatCompletionRequest {
    public String model;
    public List<Message> messages;
    public Double temperature;

    @JsonProperty("top_p")
    public Double topP;

    @JsonProperty("max_tokens")
    public Integer maxTokens;

    public ChatCompletionRequest(String model, List<Message> messages) {
        this.model = model;
        this.messages = messages;
    }

    public ChatCompletionRequest temperature(double temperature) {
        this.temperature = temperature;
        return this;
    }

    public ChatCompletionRequest topP(double topP) {
        this.topP = topP;
        return this;
    }

    public ChatCompletionRequest maxTokens(int maxTokens) {
        this.maxTokens = maxTokens;
        return this;
    }
}
