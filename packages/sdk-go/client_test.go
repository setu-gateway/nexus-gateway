package setu_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	setu "github.com/setu-gateway/setu-gateway-go"
)

func TestChatCompletionsCreate_SendsExpectedRequestAndParsesResponse(t *testing.T) {
	var gotPath, gotAuth string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotPath = r.URL.Path
		gotAuth = r.Header.Get("Authorization")
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"id":"chatcmpl-1","choices":[{"message":{"role":"assistant","content":"hi back"}}]}`))
	}))
	defer server.Close()

	client := setu.NewClient(setu.WithBaseURL(server.URL), setu.WithAPIKey("sk_setu_test"))
	resp, err := client.Chat.Completions.Create(context.Background(), setu.ChatCompletionRequest{
		Model:    "gpt-4o",
		Messages: []setu.Message{{Role: "user", Content: "hi"}},
	})
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if gotPath != "/v1/chat/completions" {
		t.Errorf("expected path /v1/chat/completions, got %s", gotPath)
	}
	if gotAuth != "Bearer sk_setu_test" {
		t.Errorf("expected Authorization header to be set, got %q", gotAuth)
	}
	if resp["id"] != "chatcmpl-1" {
		t.Errorf("expected response to be parsed, got %v", resp)
	}
}

func TestRequestFailure_ReturnsAPIError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusUnauthorized)
		_, _ = w.Write([]byte(`{"detail":"invalid key"}`))
	}))
	defer server.Close()

	client := setu.NewClient(setu.WithBaseURL(server.URL))
	_, err := client.Models.List(context.Background())
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	apiErr, ok := err.(*setu.APIError)
	if !ok {
		t.Fatalf("expected *setu.APIError, got %T: %v", err, err)
	}
	if apiErr.StatusCode != http.StatusUnauthorized {
		t.Errorf("expected status 401, got %d", apiErr.StatusCode)
	}
}

func TestConnectionFailure_ReturnsConnectionError(t *testing.T) {
	client := setu.NewClient(setu.WithBaseURL("http://127.0.0.1:1"))
	_, err := client.Models.List(context.Background())
	if err == nil {
		t.Fatal("expected an error, got nil")
	}
	if _, ok := err.(*setu.ConnectionError); !ok {
		t.Fatalf("expected *setu.ConnectionError, got %T: %v", err, err)
	}
}

// TestLiveGatewaySmoke only runs when a real gateway is reachable at the default
// base URL - skipped otherwise rather than failing CI in an environment with no
// gateway running.
func TestLiveGatewaySmoke(t *testing.T) {
	client := setu.NewClient()
	resp, err := client.Chat.Completions.Create(context.Background(), setu.ChatCompletionRequest{
		Model:    "gpt-4o",
		Messages: []setu.Message{{Role: "user", Content: "Say 'sdk-go works' and nothing else."}},
	})
	if err != nil {
		t.Skipf("no live gateway reachable at default base URL, skipping: %v", err)
	}
	if resp["id"] == nil {
		t.Errorf("expected a response with an id field, got %v", resp)
	}
}
