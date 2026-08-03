using System.Net;
using SetuGateway;

namespace SetuGateway.Tests;

/// <summary>A minimal fake HttpMessageHandler - avoids pulling in a full mocking
/// library for what's just "return this canned response, and let me inspect the
/// request that was sent".</summary>
internal class FakeHandler : HttpMessageHandler
{
    public HttpRequestMessage? LastRequest;
    private readonly HttpStatusCode _status;
    private readonly string _body;

    public FakeHandler(HttpStatusCode status, string body)
    {
        _status = status;
        _body = body;
    }

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        LastRequest = request;
        var response = new HttpResponseMessage(_status) { Content = new StringContent(_body, System.Text.Encoding.UTF8, "application/json") };
        return Task.FromResult(response);
    }
}

public class SetuClientTests
{
    [Fact]
    public async Task ChatCompletionsCreate_SendsExpectedRequestAndParsesResponse()
    {
        var handler = new FakeHandler(HttpStatusCode.OK,
            "{\"id\":\"chatcmpl-1\",\"choices\":[{\"message\":{\"role\":\"assistant\",\"content\":\"hi back\"}}]}");
        var client = new SetuClient(apiKey: "sk_setu_test", baseUrl: "http://fake", httpClient: new HttpClient(handler));

        var resp = await client.Chat.Completions.CreateAsync(
            new ChatCompletionRequest("gpt-4o", new List<Message> { new("user", "hi") }));

        Assert.Equal("chatcmpl-1", resp["id"]!.ToString());
        Assert.Equal("/v1/chat/completions", handler.LastRequest!.RequestUri!.AbsolutePath);
        Assert.Equal("Bearer", handler.LastRequest.Headers.Authorization!.Scheme);
        Assert.Equal("sk_setu_test", handler.LastRequest.Headers.Authorization!.Parameter);
    }

    [Fact]
    public async Task RequestFailure_ThrowsSetuApiException()
    {
        var handler = new FakeHandler(HttpStatusCode.Unauthorized, "{\"detail\":\"invalid key\"}");
        var client = new SetuClient(baseUrl: "http://fake", httpClient: new HttpClient(handler));

        var ex = await Assert.ThrowsAsync<SetuApiException>(() => client.Models.ListAsync());
        Assert.Equal(401, ex.StatusCode);
        Assert.Equal("invalid key", ex.Body);
    }

    [Fact]
    public async Task ConnectionFailure_ThrowsSetuConnectionException()
    {
        var client = new SetuClient(baseUrl: "http://127.0.0.1:1");
        await Assert.ThrowsAsync<SetuConnectionException>(() => client.Models.ListAsync());
    }

    [Fact]
    public async Task EmbeddingsCreate_SendsExpectedRequest()
    {
        var handler = new FakeHandler(HttpStatusCode.OK, "{\"data\":[{\"embedding\":[0.1,0.2]}]}");
        var client = new SetuClient(baseUrl: "http://fake", httpClient: new HttpClient(handler));

        var resp = await client.Embeddings.CreateAsync(new EmbeddingRequest("text-embedding-3-small", "hello"));
        Assert.NotNull(resp["data"]);
    }

    /// <summary>Only meaningful when a real gateway is reachable at the default base
    /// URL - a connection failure here is treated as "can't verify in this
    /// environment", not a test failure.</summary>
    [Fact]
    public async Task LiveGatewaySmoke()
    {
        using var client = new SetuClient();
        try
        {
            var resp = await client.Chat.Completions.CreateAsync(new ChatCompletionRequest(
                "gpt-4o", new List<Message> { new("user", "Say 'sdk-csharp works' and nothing else.") }));
            Assert.NotNull(resp["id"]);
        }
        catch (SetuConnectionException e)
        {
            Console.Error.WriteLine($"no live gateway reachable at default base URL, skipping assertion: {e.Message}");
        }
    }
}
