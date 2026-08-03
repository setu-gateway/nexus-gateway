// Package setu is the official Go client for Setu Gateway's OpenAI-compatible API.
//
//	client := setu.NewClient(setu.WithAPIKey("sk_setu_..."))
//	resp, err := client.Chat.Completions.Create(ctx, setu.ChatCompletionRequest{
//	    Model:    "gpt-4o",
//	    Messages: []setu.Message{{Role: "user", Content: "hi"}},
//	})
package setu

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"os"
	"time"
)

const defaultBaseURL = "http://localhost:8000"

// Client is the entry point for every API call. Construct with NewClient.
type Client struct {
	httpClient *http.Client
	baseURL    string
	apiKey     string

	Chat       *ChatService
	Embeddings *EmbeddingsService
	Models     *ModelsService
}

// Option configures a Client.
type Option func(*Client)

// WithAPIKey sets the Bearer token sent with every request. If omitted, the
// SETU_API_KEY environment variable is used.
func WithAPIKey(key string) Option {
	return func(c *Client) { c.apiKey = key }
}

// WithBaseURL overrides the gateway's base URL (default http://localhost:8000, or
// $SETU_BASE_URL if set).
func WithBaseURL(url string) Option {
	return func(c *Client) { c.baseURL = url }
}

// WithHTTPClient overrides the underlying *http.Client (e.g. for a custom timeout
// or transport).
func WithHTTPClient(hc *http.Client) Option {
	return func(c *Client) { c.httpClient = hc }
}

// NewClient builds a Client, applying options over the environment-derived defaults.
func NewClient(opts ...Option) *Client {
	c := &Client{
		httpClient: &http.Client{Timeout: 60 * time.Second},
		baseURL:    defaultBaseURL,
		apiKey:     os.Getenv("SETU_API_KEY"),
	}
	if v := os.Getenv("SETU_BASE_URL"); v != "" {
		c.baseURL = v
	}
	for _, opt := range opts {
		opt(c)
	}

	c.Chat = &ChatService{client: c, Completions: &chatCompletionsService{client: c}}
	c.Embeddings = &EmbeddingsService{client: c}
	c.Models = &ModelsService{client: c}
	return c
}

func (c *Client) do(ctx context.Context, method, path string, body any, out any) error {
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return err
		}
		reader = bytes.NewReader(encoded)
	}

	req, err := http.NewRequestWithContext(ctx, method, c.baseURL+path, reader)
	if err != nil {
		return err
	}
	req.Header.Set("Content-Type", "application/json")
	if c.apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+c.apiKey)
	}

	resp, err := c.httpClient.Do(req)
	if err != nil {
		return &ConnectionError{Err: err}
	}
	defer resp.Body.Close()

	respBody, err := io.ReadAll(resp.Body)
	if err != nil {
		return err
	}
	if resp.StatusCode >= 300 {
		return &APIError{StatusCode: resp.StatusCode, Body: string(respBody)}
	}
	if out != nil {
		return json.Unmarshal(respBody, out)
	}
	return nil
}

// --- Chat --------------------------------------------------------------------------

// Message is a single chat message (matches the OpenAI-compatible shape).
type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

// ChatCompletionRequest mirrors POST /v1/chat/completions's request body. Streaming
// isn't supported by this SDK yet - use ChatCompletionRequest with Stream unset
// (false) for a single complete response.
type ChatCompletionRequest struct {
	Model       string    `json:"model"`
	Messages    []Message `json:"messages"`
	Temperature *float64  `json:"temperature,omitempty"`
	TopP        *float64  `json:"top_p,omitempty"`
	MaxTokens   *int      `json:"max_tokens,omitempty"`
}

// ChatCompletionResponse is the raw, unmodeled JSON response - kept as a map so new
// gateway response fields never require an SDK update to remain readable.
type ChatCompletionResponse map[string]any

// ChatService groups chat-related calls under client.Chat, mirroring the
// gateway's own /v1/chat/completions namespace.
type ChatService struct {
	client *Client
	// Completions is accessed as client.Chat.Completions.Create(...).
	Completions *chatCompletionsService
}

type chatCompletionsService struct {
	client *Client
}

// Create sends a chat completion request and returns the parsed response.
func (s *chatCompletionsService) Create(ctx context.Context, req ChatCompletionRequest) (ChatCompletionResponse, error) {
	var out ChatCompletionResponse
	err := s.client.do(ctx, http.MethodPost, "/v1/chat/completions", req, &out)
	return out, err
}

// --- Embeddings ----------------------------------------------------------------------

// EmbeddingRequest mirrors POST /v1/embeddings's request body.
type EmbeddingRequest struct {
	Model string `json:"model"`
	Input any    `json:"input"` // string or []string
}

// EmbeddingResponse is the raw, unmodeled JSON response.
type EmbeddingResponse map[string]any

// EmbeddingsService groups embedding calls under client.Embeddings.
type EmbeddingsService struct {
	client *Client
}

// Create sends an embedding request and returns the parsed response.
func (s *EmbeddingsService) Create(ctx context.Context, req EmbeddingRequest) (EmbeddingResponse, error) {
	var out EmbeddingResponse
	err := s.client.do(ctx, http.MethodPost, "/v1/embeddings", req, &out)
	return out, err
}

// --- Models --------------------------------------------------------------------------

// ModelsResponse is the raw, unmodeled JSON response from GET /v1/models.
type ModelsResponse map[string]any

// ModelsService groups model-catalog calls under client.Models.
type ModelsService struct {
	client *Client
}

// List returns the gateway's unified model catalog.
func (s *ModelsService) List(ctx context.Context) (ModelsResponse, error) {
	var out ModelsResponse
	err := s.client.do(ctx, http.MethodGet, "/v1/models", nil, &out)
	return out, err
}
