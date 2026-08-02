# Changelog

All notable changes to Setu Gateway will be documented here. The project follows [Semantic Versioning](https://semver.org/) and uses [Keep a Changelog](https://keepachangelog.com/) conventions.

## [Unreleased]

### Added

- Intelligent request routing engine with configurable policies, per-organization
  routing rules, health/trust-based provider fallback chains, and request replay.
- Provider integrations for OpenAI, Anthropic, Gemini, Groq, and Ollama, behind a
  common plugin interface (`packages/plugin_sdk`).
- Tiered response caching and Time Machine request recording/replay for debugging.
- Scoped API keys with granular, per-key permissions.
- Redis-backed rate limiting, usage analytics, and a billing/quota foundation.
- Webhooks for delivery of gateway events, and an audit log for administrative actions.
- AI Evaluation Engine, Prompt Templates, and Request Comparison for testing prompts
  and models against each other.
- MCP (Model Context Protocol) server registration and tool invocation.
- `setu` CLI (`packages/cli`) for health checks, benchmarking, and replay from the
  command line.
- Official Python (`setu-gateway-sdk`) and TypeScript (`@setu/sdk`) client SDKs.
- React/TypeScript web dashboard for providers, models, requests, and organizations.
- Docker images and Kubernetes manifests for the gateway and dashboard.
- Public documentation site covering deployment, features, providers, plugins, the
  CLI, both SDKs, and the API reference.
- Hardened CI: unmasked lint/format/typecheck/test/security/OpenAPI-schema gates and
  a tagged-release pipeline (see [RELEASING.md](RELEASING.md)).

### Changed

- Project license changed from MIT to Apache License 2.0.

### Security

- Replaced `safety` (broken on current Python) with `pip-audit` for dependency
  scanning, and added `bandit` for static analysis of the gateway source.
