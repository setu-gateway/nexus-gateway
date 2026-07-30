import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from apps.gateway.providers.instance import model_registry, provider_registry
from packages.plugin_sdk import ChatRequest

router = APIRouter(prefix="/playground", tags=["Provider Playground"])


class PlaygroundRequest(BaseModel):
    provider: Optional[str] = Field(default=None, description="Target provider name")
    model: str = Field(description="Target model identifier")
    prompt: str = Field(description="User prompt text")
    temperature: Optional[float] = 0.7
    max_tokens: Optional[int] = 200


class PlaygroundResponse(BaseModel):
    provider: str
    model: str
    raw_response: Any
    latency_ms: float
    usage: Optional[Dict[str, int]] = None


@router.post("/completion", response_model=PlaygroundResponse)
async def run_playground_completion(req: PlaygroundRequest) -> PlaygroundResponse:
    """Execute prompt against selected provider & model, returning raw response, latency, and token usage."""
    if req.provider:
        provider_name = req.provider.lower()
        upstream_model = req.model
    else:
        provider_name, upstream_model = model_registry.resolve_provider_model(req.model)

    provider = provider_registry.get_provider(provider_name)
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Provider '{provider_name}' is not currently active or enabled.",
        )

    chat_req = ChatRequest(
        model=upstream_model,
        messages=[{"role": "user", "content": req.prompt}],
        temperature=req.temperature,
        max_tokens=req.max_tokens,
    )

    start_time = time.time()
    try:
        raw_res = await provider.chat(chat_req)
        latency_ms = round((time.time() - start_time) * 1000, 2)

        usage = None
        if isinstance(raw_res, dict) and "usage" in raw_res:
            usage = raw_res["usage"]

        return PlaygroundResponse(
            provider=provider_name,
            model=req.model,
            raw_response=raw_res,
            latency_ms=latency_ms,
            usage=usage,
        )
    except Exception as e:
        latency_ms = round((time.time() - start_time) * 1000, 2)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Playground request failed ({latency_ms}ms): {str(e)}",
        )


PLAYGROUND_HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Nexus Gateway — Provider Playground</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg: #0b0f17;
            --panel-bg: rgba(23, 31, 47, 0.7);
            --border: rgba(255, 255, 255, 0.08);
            --primary-gradient: linear-gradient(135deg, #6366f1 0%, #a855f7 50%, #ec4899 100%);
            --accent: #a855f7;
            --text: #f8fafc;
            --muted: #94a3b8;
            --success: #10b981;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg);
            color: var(--text);
            min-height: 100vh;
            display: flex;
            flex-direction: column;
        }

        header {
            border-bottom: 1px solid var(--border);
            padding: 1.25rem 2rem;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: rgba(11, 15, 23, 0.8);
            backdrop-filter: blur(12px);
        }

        .logo-title {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            font-weight: 700;
            font-size: 1.25rem;
            background: var(--primary-gradient);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .badge {
            background: rgba(168, 85, 247, 0.15);
            color: #d8b4fe;
            border: 1px solid rgba(168, 85, 247, 0.3);
            font-size: 0.75rem;
            padding: 0.25rem 0.6rem;
            border-radius: 9999px;
            font-weight: 600;
        }

        main {
            flex: 1;
            display: grid;
            grid-template-columns: 380px 1fr;
            gap: 1.5rem;
            padding: 1.5rem;
            max-width: 1600px;
            margin: 0 auto;
            width: 100%;
        }

        .panel {
            background: var(--panel-bg);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 1.5rem;
            backdrop-filter: blur(16px);
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            display: flex;
            flex-direction: column;
            gap: 1.25rem;
        }

        .form-group {
            display: flex;
            flex-direction: column;
            gap: 0.5rem;
        }

        label {
            font-size: 0.85rem;
            font-weight: 600;
            color: var(--muted);
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }

        select, input, textarea {
            background: rgba(15, 23, 42, 0.8);
            border: 1px solid var(--border);
            color: var(--text);
            padding: 0.75rem 1rem;
            border-radius: 10px;
            font-family: inherit;
            font-size: 0.95rem;
            transition: all 0.2s ease;
        }

        select:focus, input:focus, textarea:focus {
            outline: none;
            border-color: var(--accent);
            box-shadow: 0 0 0 3px rgba(168, 85, 247, 0.2);
        }

        textarea {
            resize: vertical;
            min-height: 140px;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.9rem;
        }

        button.btn-submit {
            background: var(--primary-gradient);
            color: #fff;
            border: none;
            padding: 0.85rem;
            border-radius: 10px;
            font-weight: 600;
            font-size: 1rem;
            cursor: pointer;
            transition: transform 0.15s ease, opacity 0.15s ease;
            box-shadow: 0 4px 15px rgba(168, 85, 247, 0.3);
        }

        button.btn-submit:hover {
            opacity: 0.95;
            transform: translateY(-1px);
        }

        button.btn-submit:active {
            transform: translateY(1px);
        }

        .output-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border);
        }

        .stats-bar {
            display: flex;
            gap: 1.5rem;
        }

        .stat-item {
            display: flex;
            flex-direction: column;
            align-items: flex-end;
        }

        .stat-label { font-size: 0.75rem; color: var(--muted); }
        .stat-val { font-weight: 700; color: var(--success); font-family: 'JetBrains Mono', monospace; }

        pre.code-block {
            background: #090d14;
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 1.25rem;
            color: #e2e8f0;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.88rem;
            overflow-x: auto;
            flex: 1;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    <header>
        <div class="logo-title">
            <span>⚡ Nexus Gateway</span>
            <span class="badge">Developer Playground</span>
        </div>
    </header>

    <main>
        <div class="panel">
            <div class="form-group">
                <label>Provider</label>
                <select id="providerSelect">
                    <option value="openai">OpenAI</option>
                    <option value="ollama">Ollama (Local)</option>
                    <option value="anthropic">Anthropic</option>
                    <option value="gemini">Gemini</option>
                    <option value="groq">Groq LPU</option>
                </select>
            </div>

            <div class="form-group">
                <label>Model</label>
                <input type="text" id="modelInput" value="gpt-4o" placeholder="e.g. gpt-4o, llama3.2">
            </div>

            <div class="form-group">
                <label>Prompt</label>
                <textarea id="promptInput" placeholder="Enter prompt text here...">Explain Quantum Computing in 2 simple sentences.</textarea>
            </div>

            <button class="btn-submit" onclick="runPrompt()">🚀 Send Request</button>
        </div>

        <div class="panel">
            <div class="output-header">
                <h3>Raw Response Output</h3>
                <div class="stats-bar">
                    <div class="stat-item">
                        <span class="stat-label">Latency</span>
                        <span class="stat-val" id="latencyVal">—</span>
                    </div>
                    <div class="stat-item">
                        <span class="stat-label">Tokens</span>
                        <span class="stat-val" id="tokensVal">—</span>
                    </div>
                </div>
            </div>

            <pre class="code-block" id="responseOutput">// Response output will appear here...</pre>
        </div>
    </main>

    <script>
        async function runPrompt() {
            const provider = document.getElementById('providerSelect').value;
            const model = document.getElementById('modelInput').value;
            const prompt = document.getElementById('promptInput').value;

            const outputEl = document.getElementById('responseOutput');
            const latencyEl = document.getElementById('latencyVal');
            const tokensEl = document.getElementById('tokensVal');

            outputEl.innerText = "// Executing prompt request...";
            latencyEl.innerText = "...";
            tokensEl.innerText = "...";

            try {
                const res = await fetch('/playground/completion', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ provider, model, prompt })
                });

                const data = await res.json();
                outputEl.innerText = JSON.stringify(data.raw_response || data, null, 2);
                latencyEl.innerText = data.latency_ms ? `${data.latency_ms} ms` : '—';
                tokensEl.innerText = data.usage ? `${data.usage.total_tokens || '—'}` : '—';
            } catch (err) {
                outputEl.innerText = "// Error executing request: " + err.message;
                latencyEl.innerText = "Error";
                tokensEl.innerText = "—";
            }
        }
    </script>
</body>
</html>
"""


@router.get("", response_class=HTMLResponse)
async def serve_playground_ui():
    """Serve interactive Developer Playground Web Application."""
    return HTMLResponse(content=PLAYGROUND_HTML_PAGE)
