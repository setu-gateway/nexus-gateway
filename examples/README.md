# Code Examples (`examples/`)

Six runnable examples, each in Python, TypeScript, and cURL - basic chat, streaming, embeddings, multi-provider routing, Time Machine replay, and provider comparison. Every example has been run against a live gateway; none are theoretical.

All examples default to `http://localhost:8000` (override with `SETU_BASE_URL`) and work with **no API key or provider credentials configured** - see [Installation](https://github.com/setu-gateway/nexus-gateway/blob/main/getting-started/installation.mdx) to get a gateway running first.

| # | Topic | Python | TypeScript | cURL |
|---|---|---|---|---|
| 1 | Basic chat | [`01_basic_chat.py`](python/01_basic_chat.py) | [`01-basic-chat.ts`](typescript/01-basic-chat.ts) | [`01_basic_chat.sh`](curl/01_basic_chat.sh) |
| 2 | Streaming | [`02_streaming.py`](python/02_streaming.py) | [`02-streaming.ts`](typescript/02-streaming.ts) | [`02_streaming.sh`](curl/02_streaming.sh) |
| 3 | Embeddings | [`03_embeddings.py`](python/03_embeddings.py) | [`03-embeddings.ts`](typescript/03-embeddings.ts) | [`03_embeddings.sh`](curl/03_embeddings.sh) |
| 4 | Multi-provider routing | [`04_multi_provider_routing.py`](python/04_multi_provider_routing.py) | [`04-multi-provider-routing.ts`](typescript/04-multi-provider-routing.ts) | [`04_multi_provider_routing.sh`](curl/04_multi_provider_routing.sh) |
| 5 | Time Machine replay | [`05_time_machine_replay.py`](python/05_time_machine_replay.py) | [`05-time-machine-replay.ts`](typescript/05-time-machine-replay.ts) | [`05_time_machine_replay.sh`](curl/05_time_machine_replay.sh) |
| 6 | Provider comparison | [`06_provider_comparison.py`](python/06_provider_comparison.py) | [`06-provider-comparison.ts`](typescript/06-provider-comparison.ts) | [`06_provider_comparison.sh`](curl/06_provider_comparison.sh) |

Examples 5 and 6 use raw HTTP (`httpx`/`fetch`) rather than the SDKs - `/time-machine/*` and `/routing/replay` aren't wrapped by either SDK yet.

## Running

**Python** (from `examples/python/`):

```bash
pip install -r requirements.txt
python 01_basic_chat.py
```

**TypeScript** (from the repo root, so pnpm can resolve the workspace-local `@setu/sdk`):

```bash
pnpm install
pnpm --filter @setu/examples basic-chat
# or: cd examples/typescript && npx tsx 01-basic-chat.ts
```

**cURL** (from `examples/curl/`):

```bash
./01_basic_chat.sh
# or: BASE_URL=https://your-gateway.example.com ./01_basic_chat.sh
```

## What you'll see without any provider API keys

Every provider adapter returns a deterministic, clearly-labeled mock response when its API key isn't configured (`OpenAI Reference Provider response for model '...'`, etc.) rather than failing - see [each provider's page](https://github.com/setu-gateway/nexus-gateway/blob/main/providers/openai.mdx). Add real keys to the gateway's `.env` for genuinely different, real completions. Anthropic is disabled by default (`PROVIDER_ANTHROPIC_ENABLED=true` to enable) - expect it to report a failure in examples 4 and 6 unless you've turned it on.
