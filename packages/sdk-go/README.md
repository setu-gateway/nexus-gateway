# setu-gateway-go

Official Go client for Setu Gateway.

```go
import setu "github.com/setu-gateway/setu-gateway-go"

client := setu.NewClient(setu.WithAPIKey("sk_setu_..."))
resp, err := client.Chat.Completions.Create(ctx, setu.ChatCompletionRequest{
    Model:    "gpt-4o",
    Messages: []setu.Message{{Role: "user", Content: "hi"}},
})
```

`WithAPIKey`/`WithBaseURL` fall back to `$SETU_API_KEY`/`$SETU_BASE_URL` when omitted.

## Not yet supported

Streaming (`stream: true`) isn't implemented in this SDK yet - use the Python or
TypeScript SDK if you need server-sent-event streaming today. `Chat.Completions.Create`,
`Embeddings.Create`, and `Models.List` are fully implemented and covered by tests,
including a live smoke test against a running gateway.

## Verify

```bash
go build ./...
go vet ./...
go test ./...
```
