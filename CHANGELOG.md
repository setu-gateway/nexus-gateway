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
- Enterprise Policy Engine: organization-wide guardrails (provider allow/denylist,
  minimum context window, secret-pattern blocking) enforced before routing.
- AI Cost Optimizer: cheaper-model recommendations based on an organization's actual
  recorded usage, not a generic price list.
- AI Traffic Replay: batch replay of historical Time Machine records against a
  candidate provider, with aggregate success rate, latency, and similarity reporting.
- AI Gateway Studio: a dashboard UI for building routing rules, simulating routing
  policies, and testing prompts across providers side by side.
- Community dashboard page showing live GitHub repository activity.
- Provider certification (`setu certify`): a six-check contract (chat, streaming,
  embeddings, retry, health, authentication) a provider plugin must pass to be
  marketplace-listed.
- Plugin marketplace skeleton: manifest schema, local registry, `setu marketplace
  validate` CLI command, and a subprocess-isolated plugin execution sandbox
  (`apps/gateway/plugins/sandbox.py`) with wall-clock, CPU, and (Linux) memory limits.
- Official Go, Rust, Java, and C# SDKs, joining the existing Python and TypeScript
  clients.
- Terraform provider, Helm chart, and Kubernetes Operator for declarative deployment
  and lifecycle management, each verified against a real environment (a live
  gateway, `helm template`/`helm lint`, and a local `kind` cluster respectively).
- Dependency-vulnerability scanning in CI for the four new SDK/infrastructure
  language ecosystems (`govulncheck`, `cargo audit`, `dotnet list package
  --vulnerable`, OWASP dependency-check) plus a PR-diff-wide dependency review.
- Public marketing website (`apps/website`), governance and maintainers documents,
  and a staged public roadmap and growth plan.
- Sprint 7 features (Policy Engine, Cost Optimizer, Traffic Replay, Plugin
  Marketplace, Provider Certification, Terraform provider, Helm chart, Kubernetes
  Operator, and the four new SDKs) wired into the documentation site's navigation.
- Deployment packaging for the website and marketplace registry
  (`Dockerfile.website`, `Dockerfile.marketplace`), a Caddy reverse-proxy example
  with automatic HTTPS for publicly exposing the gateway/dashboard, and
  [`DEPLOYMENT_RUNBOOK.md`](DEPLOYMENT_RUNBOOK.md) walking through all three -
  stops short of creating hosting accounts or registering a domain, which remain a
  deliberate, user-driven decision.

### Changed

- Project license changed from MIT to Apache License 2.0.

### Security

- Replaced `safety` (broken on current Python) with `pip-audit` for dependency
  scanning, and added `bandit` for static analysis of the gateway source.
