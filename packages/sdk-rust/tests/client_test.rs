use setu_gateway::{ChatCompletionRequest, Client, Error, Message};
use wiremock::matchers::{header, method, path};
use wiremock::{Mock, MockServer, ResponseTemplate};

#[tokio::test]
async fn chat_completions_create_sends_expected_request_and_parses_response() {
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .and(path("/v1/chat/completions"))
        .and(header("Authorization", "Bearer sk_setu_test"))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "id": "chatcmpl-1",
            "choices": [{"message": {"role": "assistant", "content": "hi back"}}]
        })))
        .mount(&server)
        .await;

    let client = Client::new().with_base_url(server.uri()).with_api_key("sk_setu_test");
    let resp = client
        .chat()
        .completions()
        .create(ChatCompletionRequest {
            model: "gpt-4o".into(),
            messages: vec![Message { role: "user".into(), content: "hi".into() }],
            temperature: None,
            top_p: None,
            max_tokens: None,
        })
        .await
        .expect("request should succeed");

    assert_eq!(resp["id"], "chatcmpl-1");
}

#[tokio::test]
async fn request_failure_returns_api_error() {
    let server = MockServer::start().await;
    Mock::given(method("GET"))
        .and(path("/v1/models"))
        .respond_with(ResponseTemplate::new(401).set_body_json(serde_json::json!({"detail": "invalid key"})))
        .mount(&server)
        .await;

    let client = Client::new().with_base_url(server.uri());
    let err = client.models().list().await.expect_err("expected an error");
    match err {
        Error::Api { status, body } => {
            assert_eq!(status, 401);
            assert_eq!(body, "invalid key");
        }
        other => panic!("expected Error::Api, got {other:?}"),
    }
}

#[tokio::test]
async fn connection_failure_returns_connection_error() {
    let client = Client::new().with_base_url("http://127.0.0.1:1");
    let err = client.models().list().await.expect_err("expected an error");
    assert!(matches!(err, Error::Connection(_)), "expected Error::Connection, got {err:?}");
}

/// Only runs meaningfully when a real gateway is reachable at the default base URL;
/// otherwise the connection error path itself is still exercised (so the test isn't
/// flaky either way, it just can't prove the live round-trip in that environment).
#[tokio::test]
async fn live_gateway_smoke() {
    let client = Client::new();
    match client
        .chat()
        .completions()
        .create(ChatCompletionRequest {
            model: "gpt-4o".into(),
            messages: vec![Message { role: "user".into(), content: "Say 'sdk-rust works' and nothing else.".into() }],
            temperature: None,
            top_p: None,
            max_tokens: None,
        })
        .await
    {
        Ok(resp) => assert!(resp.get("id").is_some(), "expected a response with an id field, got {resp:?}"),
        Err(Error::Connection(_)) => eprintln!("no live gateway reachable at default base URL, skipping assertion"),
        Err(e) => panic!("unexpected error: {e:?}"),
    }
}
