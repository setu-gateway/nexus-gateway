# Setu Gateway Java SDK

Official Java client for Setu Gateway (Java 11+, Maven).

```java
SetuClient client = new SetuClient.Builder().apiKey("sk_setu_...").build();
JsonNode resp = client.chat().completions().create(
    new ChatCompletionRequest("gpt-4o", List.of(new Message("user", "hi"))));
```

`Builder()` reads `$SETU_BASE_URL` (default `http://localhost:8000`) and
`$SETU_API_KEY` by default; override with `.baseUrl(...)` / `.apiKey(...)`.

## Not yet supported

Streaming (`stream: true`) isn't implemented in this SDK yet - use the Python or
TypeScript SDK if you need server-sent-event streaming today.

## Verify

```bash
mvn test
```

Uses `java.net.http.HttpClient` pinned to HTTP/1.1 - the JDK's default HTTP/2
preference attempts an "h2c" upgrade handshake that a plain-HTTP uvicorn server
doesn't understand, surfacing as a confusing raw "Invalid HTTP request received"
rather than a normal HTTP error.
