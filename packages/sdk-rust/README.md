# setu-gateway (Rust)

Official Rust client for Setu Gateway.

```rust
let client = setu_gateway::Client::new().with_api_key("sk_setu_...");
let resp = client.chat().completions().create(setu_gateway::ChatCompletionRequest {
    model: "gpt-4o".into(),
    messages: vec![setu_gateway::Message { role: "user".into(), content: "hi".into() }],
    temperature: None,
    top_p: None,
    max_tokens: None,
}).await?;
```

`Client::new()` reads `$SETU_BASE_URL` (default `http://localhost:8000`) and
`$SETU_API_KEY`; override with `.with_base_url()` / `.with_api_key()`.

## Not yet supported

Streaming (`stream: true`) isn't implemented in this crate yet - use the Python or
TypeScript SDK if you need server-sent-event streaming today. `chat().completions().create()`,
`embeddings().create()`, and `models().list()` are fully implemented and covered by
tests (mocked via `wiremock`, plus a live smoke test against a running gateway).

## Verify

```bash
cargo build
cargo test
cargo clippy --all-targets
```
