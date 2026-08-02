from fastapi.testclient import TestClient

from apps.gateway.main import app

client = TestClient(app)


def test_openai_sdk_models_list_compatibility():
    """Verify GET /v1/models returns strict OpenAI SDK spec."""
    resp = client.get("/v1/models")
    assert resp.status_code == 200
    body = resp.json()

    assert body["object"] == "list"
    assert isinstance(body["data"], list)
    assert len(body["data"]) > 0

    first_model = body["data"][0]
    assert "id" in first_model
    assert first_model["object"] == "model"
    assert "created" in first_model
    assert "owned_by" in first_model


def test_openai_sdk_chat_completion_compatibility():
    """Verify POST /v1/chat/completions returns strict OpenAI SDK spec."""
    payload = {
        "model": "gpt-4o",
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Hello OpenAI!"},
        ],
        "temperature": 0.7,
        "max_tokens": 100,
    }

    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "chat.completion"
    assert data["model"] == "gpt-4o"
    assert "id" in data
    assert "created" in data
    assert "choices" in data
    assert len(data["choices"]) > 0

    choice = data["choices"][0]
    assert choice["index"] == 0
    assert choice["message"]["role"] == "assistant"
    assert "content" in choice["message"]
    assert "finish_reason" in choice


def test_openai_sdk_streaming_chat_completion_compatibility():
    """Verify POST /v1/chat/completions with stream=True returns valid SSE chunk format."""
    payload = {
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Tell me a joke"}],
        "stream": True,
    }

    resp = client.post("/v1/chat/completions", json=payload)
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]

    lines = [line.strip() for line in resp.text.split("\n") if line.strip()]
    data_lines = [line for line in lines if line.startswith("data: ")]

    assert len(data_lines) > 0
    assert data_lines[-1] == "data: [DONE]"


def test_openai_sdk_embeddings_compatibility():
    """Verify POST /v1/embeddings returns strict OpenAI SDK spec."""
    payload = {
        "model": "text-embedding-3-small",
        "input": ["Search query text 1", "Search query text 2"],
    }

    resp = client.post("/v1/embeddings", json=payload)
    assert resp.status_code == 200
    data = resp.json()

    assert data["object"] == "list"
    assert "data" in data
    assert len(data["data"]) > 0

    emb_item = data["data"][0]
    assert emb_item["object"] == "embedding"
    assert "embedding" in emb_item
    assert isinstance(emb_item["embedding"], list)
