//! Official Rust client for Setu Gateway's OpenAI-compatible API.
//!
//! ```no_run
//! # async fn example() -> Result<(), setu_gateway::Error> {
//! let client = setu_gateway::Client::new().with_api_key("sk_setu_...");
//! let resp = client.chat().completions().create(setu_gateway::ChatCompletionRequest {
//!     model: "gpt-4o".into(),
//!     messages: vec![setu_gateway::Message { role: "user".into(), content: "hi".into() }],
//!     temperature: None,
//!     top_p: None,
//!     max_tokens: None,
//! }).await?;
//! # let _ = resp;
//! # Ok(())
//! # }
//! ```
//!
//! Streaming (`stream: true`) isn't implemented yet - use the Python or TypeScript
//! SDK if you need server-sent-event streaming today.

use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::env;

const DEFAULT_BASE_URL: &str = "http://localhost:8000";

#[derive(Debug, thiserror::Error)]
pub enum Error {
    #[error("setu gateway request failed ({status}): {body}")]
    Api { status: u16, body: String },
    #[error("could not reach setu gateway: {0}")]
    Connection(#[from] reqwest::Error),
}

#[derive(Debug, Clone, Serialize)]
pub struct Message {
    pub role: String,
    pub content: String,
}

#[derive(Debug, Clone, Serialize)]
pub struct ChatCompletionRequest {
    pub model: String,
    pub messages: Vec<Message>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub temperature: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub top_p: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub max_tokens: Option<u32>,
}

#[derive(Debug, Clone, Serialize)]
pub struct EmbeddingRequest {
    pub model: String,
    pub input: Value, // string or array of strings
}

/// The gateway's response, kept as raw JSON so a new field never requires an SDK
/// update to remain readable.
pub type ApiResponse = Value;

#[derive(Debug, Deserialize)]
struct ErrorBody {
    #[serde(default)]
    detail: Option<String>,
}

/// Entry point for every API call. Construct with `Client::new()`.
#[derive(Clone)]
pub struct Client {
    http: reqwest::Client,
    base_url: String,
    api_key: Option<String>,
}

impl Default for Client {
    fn default() -> Self {
        Self::new()
    }
}

impl Client {
    /// Builds a client using `$SETU_BASE_URL` (default `http://localhost:8000`) and
    /// `$SETU_API_KEY` as defaults - override either with `.with_base_url()` /
    /// `.with_api_key()`.
    pub fn new() -> Self {
        Self {
            http: reqwest::Client::new(),
            base_url: env::var("SETU_BASE_URL").unwrap_or_else(|_| DEFAULT_BASE_URL.to_string()),
            api_key: env::var("SETU_API_KEY").ok(),
        }
    }

    pub fn with_base_url(mut self, base_url: impl Into<String>) -> Self {
        self.base_url = base_url.into();
        self
    }

    pub fn with_api_key(mut self, api_key: impl Into<String>) -> Self {
        self.api_key = Some(api_key.into());
        self
    }

    async fn request<B: Serialize>(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<&B>,
    ) -> Result<ApiResponse, Error> {
        let mut req = self.http.request(method, format!("{}{}", self.base_url, path));
        if let Some(key) = &self.api_key {
            req = req.bearer_auth(key);
        }
        if let Some(b) = body {
            req = req.json(b);
        }

        let resp = req.send().await?;
        let status = resp.status();
        let text = resp.text().await?;

        if !status.is_success() {
            let message = serde_json::from_str::<ErrorBody>(&text)
                .ok()
                .and_then(|e| e.detail)
                .unwrap_or(text);
            return Err(Error::Api { status: status.as_u16(), body: message });
        }

        serde_json::from_str(&text).map_err(|e| Error::Api {
            status: status.as_u16(),
            body: format!("could not parse response as JSON: {e}"),
        })
    }

    pub fn chat(&self) -> Chat<'_> {
        Chat { client: self }
    }

    pub fn embeddings(&self) -> Embeddings<'_> {
        Embeddings { client: self }
    }

    pub fn models(&self) -> Models<'_> {
        Models { client: self }
    }
}

pub struct Chat<'a> {
    client: &'a Client,
}

impl<'a> Chat<'a> {
    pub fn completions(&self) -> ChatCompletions<'a> {
        ChatCompletions { client: self.client }
    }
}

pub struct ChatCompletions<'a> {
    client: &'a Client,
}

impl ChatCompletions<'_> {
    pub async fn create(&self, req: ChatCompletionRequest) -> Result<ApiResponse, Error> {
        self.client.request(reqwest::Method::POST, "/v1/chat/completions", Some(&req)).await
    }
}

pub struct Embeddings<'a> {
    client: &'a Client,
}

impl Embeddings<'_> {
    pub async fn create(&self, req: EmbeddingRequest) -> Result<ApiResponse, Error> {
        self.client.request(reqwest::Method::POST, "/v1/embeddings", Some(&req)).await
    }
}

pub struct Models<'a> {
    client: &'a Client,
}

impl Models<'_> {
    pub async fn list(&self) -> Result<ApiResponse, Error> {
        self.client.request::<()>(reqwest::Method::GET, "/v1/models", None).await
    }
}
