using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace SetuGateway;

/// <summary>
/// Official C# client for Setu Gateway's OpenAI-compatible API.
/// <code>
/// var client = new SetuClient(apiKey: "sk_setu_...");
/// var resp = await client.Chat.Completions.CreateAsync(new ChatCompletionRequest(
///     "gpt-4o", new List&lt;Message&gt; { new("user", "hi") }));
/// </code>
/// Streaming (<c>stream=true</c>) isn't supported by this SDK yet - use the Python
/// or TypeScript SDK if you need server-sent-event streaming today.
/// </summary>
public class SetuClient : IDisposable
{
    private const string DefaultBaseUrl = "http://localhost:8000";

    private readonly HttpClient _http;
    private readonly string _baseUrl;

    public ChatNamespace Chat { get; }
    public EmbeddingsNamespace Embeddings { get; }
    public ModelsNamespace Models { get; }

    public SetuClient(string? apiKey = null, string? baseUrl = null, HttpClient? httpClient = null)
    {
        _baseUrl = (baseUrl ?? Environment.GetEnvironmentVariable("SETU_BASE_URL") ?? DefaultBaseUrl).TrimEnd('/');
        _http = httpClient ?? new HttpClient();

        var key = apiKey ?? Environment.GetEnvironmentVariable("SETU_API_KEY");
        if (!string.IsNullOrEmpty(key))
        {
            _http.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", key);
        }

        Chat = new ChatNamespace(this);
        Embeddings = new EmbeddingsNamespace(this);
        Models = new ModelsNamespace(this);
    }

    internal async Task<JsonNode> RequestAsync(HttpMethod method, string path, object? body = null)
    {
        HttpResponseMessage response;
        try
        {
            using var request = new HttpRequestMessage(method, _baseUrl + path);
            if (body != null)
            {
                request.Content = JsonContent.Create(body);
            }
            response = await _http.SendAsync(request).ConfigureAwait(false);
        }
        catch (HttpRequestException e)
        {
            throw new SetuConnectionException(_baseUrl, e);
        }

        var text = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
        if (!response.IsSuccessStatusCode)
        {
            string message = text;
            try
            {
                var errorNode = JsonNode.Parse(text);
                if (errorNode?["detail"] != null)
                {
                    message = errorNode["detail"]!.ToString();
                }
            }
            catch (JsonException)
            {
                // response body wasn't JSON - fall back to the raw text already assigned above.
            }
            throw new SetuApiException((int)response.StatusCode, message);
        }

        return JsonNode.Parse(text) ?? new JsonObject();
    }

    public void Dispose() => _http.Dispose();
}

public class ChatNamespace
{
    public ChatCompletionsNamespace Completions { get; }

    internal ChatNamespace(SetuClient client)
    {
        Completions = new ChatCompletionsNamespace(client);
    }
}

public class ChatCompletionsNamespace
{
    private readonly SetuClient _client;

    internal ChatCompletionsNamespace(SetuClient client) => _client = client;

    public Task<JsonNode> CreateAsync(ChatCompletionRequest request) =>
        _client.RequestAsync(HttpMethod.Post, "/v1/chat/completions", request);
}

public class EmbeddingsNamespace
{
    private readonly SetuClient _client;

    internal EmbeddingsNamespace(SetuClient client) => _client = client;

    public Task<JsonNode> CreateAsync(EmbeddingRequest request) =>
        _client.RequestAsync(HttpMethod.Post, "/v1/embeddings", request);
}

public class ModelsNamespace
{
    private readonly SetuClient _client;

    internal ModelsNamespace(SetuClient client) => _client = client;

    public Task<JsonNode> ListAsync() => _client.RequestAsync(HttpMethod.Get, "/v1/models");
}
