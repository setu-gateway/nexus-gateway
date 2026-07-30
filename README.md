<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="logo/dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="logo/light.svg">
    <img alt="Setu Gateway" src="logo/light.svg" width="360">
  </picture>
</p>

<p align="center">
  <b>Setu</b> (सेतु) means "bridge." Setu Gateway is the bridge between your applications and every LLM provider.
</p>

<p align="center">
  <a href="https://github.com/setu-gateway/nexus-gateway/actions/workflows/ci.yml"><img src="https://github.com/setu-gateway/nexus-gateway/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT"></a>
  <a href="CONTRIBUTING.md"><img src="https://img.shields.io/badge/PRs-welcome-blueviolet.svg" alt="PRs Welcome"></a>
  <a href="rfcs/"><img src="https://img.shields.io/badge/RFCs-13%20accepted-blue.svg" alt="RFCs"></a>
</p>

---

## What is Setu Gateway?

Setu Gateway is an open-source, self-hostable **AI gateway**: a single OpenAI-compatible API in front of every LLM provider you use — OpenAI, Anthropic, Google Gemini, Ollama, Groq, OpenRouter, and more.

Point your existing OpenAI SDK at Setu instead of directly at a provider, and get:

- 🔀 **Intelligent routing** — capability-aware model selection, health-aware fallback chains, and explainable routing decisions (RFC-0005).
- 🔌 **One API, every provider** — chat, embeddings, images, and audio behind the same OpenAI-compatible surface (RFC-0004, RFC-0010).
- 🧩 **A real plugin system** — providers, auth, billing, firewalls, and cache backends are plugins behind a versioned SDK, not hardcoded conditionals (RFC-0009).
- 🔐 **Security by default** — zero-trust request handling, scoped/hashed API keys, encrypted provider credentials, per-organization tenant isolation (RFC-0003, RFC-0007).
- 📊 **Observability built in** — OpenTelemetry, Prometheus, Grafana, Loki, and Tempo out of the box (RFC-0011).
- 🏠 **No lock-in** — Docker Compose for self-hosting, Kubernetes/Helm for scale, and an explicit no-vendor-lock-in principle (RFC-0000, RFC-0002).

Every feature in this project has to earn its place by making AI infrastructure **faster, cheaper, smarter, safer, or easier** — see [RFC-0000](rfcs/RFC-0000.md).

> **Status:** Setu Gateway is pre-release and under active development (see the [ROADMAP](ROADMAP.md)). APIs and schemas may still change. Follow along, try it locally, and help shape v1.

## Quickstart

The fastest way to run Setu Gateway locally is Docker Compose:

```bash
git clone https://github.com/setu-gateway/nexus-gateway.git
cd nexus-gateway
cp .env.example .env
docker compose up -d
```

This starts the gateway, dashboard, PostgreSQL, and Redis. The gateway listens on `http://localhost:8000`.

Send your first request — it's OpenAI-compatible, so existing SDKs work unchanged:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SETU_API_KEY" \
  -d '{
        "model": "gpt-4o",
        "messages": [{"role": "user", "content": "Hello, Setu!"}]
      }'
```

Prefer running from source? See the [development setup guide](contributing/development.mdx).

## How it's built

Setu is a monorepo (see [RFC-0001](rfcs/RFC-0001.md)):

| Path | What lives there |
| --- | --- |
| [`apps/gateway`](apps/gateway) | The Python/FastAPI gateway — routing, auth, providers, plugins, database models |
| [`apps/dashboard`](apps/dashboard) | Web dashboard for metrics, routing config, and API key management |
| [`apps/playground`](apps/playground) | Interactive prompt/API playground |
| [`apps/docs`](apps/docs) | Documentation site |
| [`packages/`](packages) | Plugin SDK, provider SDK, OpenAPI contract, shared utilities |
| [`plugins/`](plugins) | Provider adapters (OpenAI, Anthropic, Gemini, Groq, Ollama) and other first-party plugins |
| [`infrastructure/`](infrastructure) | Docker, Kubernetes/Helm, Terraform, monitoring config |
| [`rfcs/`](rfcs) | Every accepted architectural decision behind this project |
| [`tests/`](tests) | Unit and integration tests |

The backend is Python 3.13+, FastAPI, SQLAlchemy 2, PostgreSQL, and Redis. The web apps are React, TypeScript, and Tailwind. See [RFC-0002](rfcs/RFC-0002.md) for the full system architecture.

## Documentation

- **New to Setu?** Start with [Introduction](getting-started/introduction.mdx) → [Installation](getting-started/installation.mdx) → [Quickstart](getting-started/quickstart.mdx).
- **Configuring providers?** See [`providers/`](providers) for OpenAI, Anthropic, Google, Ollama, and OpenRouter setup.
- **Writing a plugin?** See [Plugin overview](plugins/overview.mdx) and [Creating plugins](plugins/creating-plugins.mdx).
- **Curious about a design decision?** Every major decision is an [RFC](rfcs) — start with [RFC-0000: Engineering Principles](rfcs/RFC-0000.md).

## Contributing

Setu Gateway is built in the open, and contributions are welcome — bug fixes, new providers, plugins, tests, and documentation all count.

1. Read [CONTRIBUTING.md](CONTRIBUTING.md) and the relevant [RFC](rfcs).
2. Check open [issues](https://github.com/setu-gateway/nexus-gateway/issues), especially ones labeled `good first issue`.
3. Open a pull request from a short-lived branch off `main` using [Conventional Commits](https://www.conventionalcommits.org/).

Please also read our [Code of Conduct](CODE_OF_CONDUCT.md). Found a security issue? Do not open a public issue — see [SECURITY.md](SECURITY.md) for responsible disclosure.

## License

[MIT](LICENSE) © Setu Gateway Contributors
