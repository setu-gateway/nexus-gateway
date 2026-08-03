# SetuGateway (C#)

Official C# client for Setu Gateway (.NET 8+).

```csharp
using var client = new SetuClient(apiKey: "sk_setu_...");
var resp = await client.Chat.Completions.CreateAsync(new ChatCompletionRequest(
    "gpt-4o", new List<Message> { new("user", "hi") }));
```

The constructor reads `SETU_BASE_URL` (default `http://localhost:8000`) and
`SETU_API_KEY` from the environment by default; pass `baseUrl`/`apiKey` explicitly
to override.

## Not yet supported

Streaming (`stream: true`) isn't implemented in this SDK yet - use the Python or
TypeScript SDK if you need server-sent-event streaming today.

## Verify

```bash
dotnet build
dotnet test
```
