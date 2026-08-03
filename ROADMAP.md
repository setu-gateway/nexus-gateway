# Setu Gateway Roadmap

The roadmap is directional, not a promise - priorities shift as real usage and
contributions come in. For what's already shipped, see [CHANGELOG.md](CHANGELOG.md).

Versions are staged by maturity rather than jumping straight to a 1.0 feature list:
each stage has a concrete exit criterion, not just a feature checklist, so "done" is
unambiguous before moving to the next one.

## v0.1.0-alpha — Core platform (current)

The gateway itself: routing, auth/RBAC, caching, Time Machine, analytics, billing
foundation, webhooks, audit log, the CLI, and the Python/TypeScript SDKs. Exit
criterion: a developer can self-host it, route real traffic across 5 providers, and
manage it through the dashboard without touching the database directly.

## v0.2.0-beta — Ecosystem

- Plugin Marketplace - discover and install community-built plugins beyond what
  ships in this repo, with the certification contract (`setu certify`) as the
  trust signal for a listed plugin.
- Mistral provider integration - the remaining gap in bundled provider coverage.
- AI Workflow Engine - chaining multiple requests/providers into a single defined
  pipeline, beyond today's single-request routing.
- MCP enhancements - more transport options, richer tool-call handling, beyond the
  registration/invocation foundation shipped in v0.1.0-alpha.
- Additional SDKs (Go, Java, Rust, C#) alongside the existing Python/TypeScript ones.
- Terraform provider and Helm chart for declarative, enterprise-friendly deployment.

Exit criterion: a plugin built by someone outside this repo can be certified,
installed, and routed to without a gateway code change.

## v0.5.0 — Enterprise readiness

- Enterprise SSO (SAML/OIDC) for dashboard and API access.
- Enterprise Policy Engine hardening - the guardrail primitives (provider
  allow/denylist, minimum context window, secret scanning) shipped in
  v0.1.0-alpha, expanded with more policy types as real enterprise use cases
  surface them.
- Multi-region deployment support.
- Kubernetes Operator for automated lifecycle management (upgrades, health
  recovery, secret rotation) beyond what the Helm chart covers.
- High availability guidance and tooling for the gateway and its datastores.

Exit criterion: a security/compliance team can adopt Setu Gateway using their
existing SSO and policy requirements without a bespoke integration.

## v1.0.0 — Stable

- A frozen, stable public API with a documented deprecation policy.
- Long-term support (LTS) commitments for stable releases.
- Enterprise-grade documentation (SLAs, support channels, compliance references).

Exit criterion: a breaking change to the public API requires a major version bump,
full stop - no exceptions carved out after this point.

## Deliberately not on this roadmap yet

A hosted, publicly-reachable Setu Gateway demo/playground and a live plugin
marketplace-as-a-service both need real infrastructure (hosting, a domain, ongoing
moderation for third-party code) that's a hosting/business decision, not an
engineering one - they'll get scheduled once that decision is made, not before. The
engineering side of "reachable the moment that decision is made" is done
(`DEPLOYMENT_RUNBOOK.md`); what's left is genuinely the decision itself, plus (for
the marketplace specifically) reviewer capacity for third-party submissions.

## Have a request?

Open a [feature request](https://github.com/setu-gateway/nexus-gateway/issues/new/choose)
or start a [discussion](https://github.com/setu-gateway/nexus-gateway/discussions) -
roadmap priorities are shaped by what the community actually needs.
