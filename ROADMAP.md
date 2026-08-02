# Setu Gateway Roadmap

The roadmap is directional, not a promise - priorities shift as real usage and
contributions come in. For what's already shipped, see [CHANGELOG.md](CHANGELOG.md).

## v0.2 — Provider expansion

- Mistral provider integration.
- Anthropic, Gemini, and Groq are already real integrations as of v0.1.0 - the
  remaining gap in provider coverage is Mistral.

## v0.3 — Extensibility

- Plugin Marketplace - a way to discover and install community-built plugins, rather
  than only the ones bundled in this repo.
- AI Workflow Engine - chaining multiple requests/providers into a single defined
  pipeline, beyond today's single-request routing.
- MCP enhancements - v0.1.0 ships server registration and tool invocation as a
  foundation; this expands on it (more transport options, richer tool-call handling).

## v0.4 — Enterprise readiness

- Enterprise SSO (SAML/OIDC) for dashboard and API access.
- Multi-region deployment support.
- High availability guidance and tooling for the gateway and its datastores.

## v1.0 — Stable

- A frozen, stable public API with a documented deprecation policy.
- Long-term support (LTS) commitments for stable releases.
- Enterprise-grade documentation (SLAs, support channels, compliance references).

## Have a request?

Open a [feature request](https://github.com/setu-gateway/nexus-gateway/issues/new/choose)
or start a [discussion](https://github.com/setu-gateway/nexus-gateway/discussions) -
roadmap priorities are shaped by what the community actually needs.
