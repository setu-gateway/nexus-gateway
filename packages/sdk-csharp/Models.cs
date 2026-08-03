using System.Text.Json.Serialization;

namespace SetuGateway;

/// <summary>A single chat message, matching the OpenAI-compatible shape.</summary>
public class Message
{
    [JsonPropertyName("role")]
    public string Role { get; set; }

    [JsonPropertyName("content")]
    public string Content { get; set; }

    public Message(string role, string content)
    {
        Role = role;
        Content = content;
    }
}

/// <summary>Mirrors POST /v1/chat/completions's request body. Streaming
/// (stream=true) isn't supported by this SDK yet - construct without it for a
/// single complete response.</summary>
public class ChatCompletionRequest
{
    [JsonPropertyName("model")]
    public string Model { get; set; }

    [JsonPropertyName("messages")]
    public List<Message> Messages { get; set; }

    [JsonPropertyName("temperature")]
    public double? Temperature { get; set; }

    [JsonPropertyName("top_p")]
    public double? TopP { get; set; }

    [JsonPropertyName("max_tokens")]
    public int? MaxTokens { get; set; }

    public ChatCompletionRequest(string model, List<Message> messages)
    {
        Model = model;
        Messages = messages;
    }
}

/// <summary>Mirrors POST /v1/embeddings's request body. <c>Input</c> is
/// <c>object</c> because it may be a single string or a list of strings, matching
/// the OpenAI-compatible API.</summary>
public class EmbeddingRequest
{
    [JsonPropertyName("model")]
    public string Model { get; set; }

    [JsonPropertyName("input")]
    public object Input { get; set; }

    public EmbeddingRequest(string model, object input)
    {
        Model = model;
        Input = input;
    }
}
