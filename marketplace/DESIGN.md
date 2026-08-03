# Plugin Marketplace - design

This directory is the marketplace **skeleton**: a manifest schema
([`schema/plugin-manifest.schema.json`](schema/plugin-manifest.schema.json)), a
local registry file ([`registry.json`](registry.json)), and a CLI validator
(`setu marketplace validate`). It is not a live, hosted service - per
[ROADMAP.md](../ROADMAP.md), that needs a hosting/moderation decision this
skeleton deliberately doesn't make on its own.

## Why not a live service yet

"Anyone can publish plugins" means arbitrary third-party code running inside (or
alongside) the gateway. That's a real, ongoing security surface - not something to
stand up in a rush. A plugin can:

- Make outbound network calls (a malicious provider plugin could exfiltrate prompt
  content to a third party under the guise of "calling the model").
- Read `PluginContext.headers`/`state`, which can carry request metadata.
- Run arbitrary Python at import time.
- Hang, leak memory, or otherwise misbehave badly enough to affect the gateway
  process it shares.

None of that is unique to this project - it's the same trust model every plugin
ecosystem (npm, PyPI, VS Code extensions) has to solve - but it's also exactly why
"let's just accept PRs to a registry repo" needs the review process below before it
opens to the public, not a rubber stamp.

**Update**: the last item is now solved. `apps/gateway/plugins/sandbox.py`'s
`SandboxedPluginRunner` runs a plugin's hooks in an isolated subprocess with a
wall-clock timeout, a CPU-time limit, and (on Linux) a memory ceiling - verified
against real misbehaving plugins (an infinite loop, a memory bomb, a plugin that
raises) as well as the real bundled `hello_world` plugin, in
`tests/test_plugin_sandbox.py`. It does **not** solve the first two items -
network egress and reading data it's explicitly handed remain open, and are
inherent to giving a plugin any ability to act on a request at all. It's also not
yet wired to anything: there is no live "install a marketplace plugin" pipeline for
it to sandbox the execution of, since that pipeline is itself one of the things
below still needing a hosting decision. Once that pipeline exists, running every
non-bundled plugin's hooks through `SandboxedPluginRunner` rather than
`PluginLoader`'s direct in-process calls is the intended integration point.

## Submission and review workflow (once hosted)

1. **Submit**: a PR against a `setu-gateway/marketplace` registry repo, adding one
   entry to `registry.json` that validates against `plugin-manifest.schema.json`.
   The plugin's own code lives in the *author's* repository (`repository` field) -
   the registry only ever stores the manifest, never a copy of third-party code.
2. **Automated checks** (CI on the PR):
   - Schema validation (`setu marketplace validate`).
   - For `category: providers`: `setu certify <plugin>` must report `certified: true`
     (see [Epic 7.4](../apps/gateway/certification)) - a provider plugin that fails
     chat/streaming/embeddings/retry/health/auth checks doesn't get listed.
   - Static scan of the linked repository (dependency vulnerability scan, secret
     scan) - tooling already in this repo's own CI
     ([`.github/workflows/security.yml`](../.github/workflows/security.yml)) is the
     starting point, not something to reinvent.
3. **Manual review**: a maintainer (see [GOVERNANCE.md](../GOVERNANCE.md)) reads the
   linked repository before approving - automated checks catch known patterns, not
   novel malicious behavior. This is the step that doesn't scale past a handful of
   submissions a week without more reviewers, which is itself a reason to grow
   [MAINTAINERS.md](../MAINTAINERS.md) before opening this widely.
4. **Merge**: the manifest lands in `registry.json`; the dashboard's marketplace
   view (not yet built - see [Epic 7.3](../ROADMAP.md)) reads directly from this
   file once it's hosted somewhere fetchable (a static site, a CDN-backed JSON
   endpoint - deliberately not decided here).
5. **Ongoing**: a listed plugin whose repository starts failing certification (a
   regression, an abandoned project) gets flagged, not silently removed - the
   `certification` field's `checkedAt` timestamp makes staleness visible.

## Categories

Matches [Epic 7.3](../ROADMAP.md)'s list, enforced by the schema's `category` enum:
providers, authentication, analytics, caching, billing, routing-policies,
notifications, storage, vector-databases.

## What "skeleton" means here, concretely

**Update**: "a place to host `registry.json` publicly" is now solved, two ways - see
[`DEPLOYMENT_RUNBOOK.md`](../DEPLOYMENT_RUNBOOK.md#3-marketplace-registry-marketplaceregistryjson).
The zero-infrastructure option (this repository's own `raw.githubusercontent.com`
content, once a change is pushed to `main`) needs no new hosting decision at all; a
`Dockerfile.marketplace` also exists for self-hosting independent of GitHub, built
and `curl`-verified serving `registry.json` with the right content type and CORS
during this pass. What's still genuinely unsolved is the submission/review
*workflow*, not the hosting - the row below is unchanged.

| Built now | Needs a hosting decision first |
| --- | --- |
| Manifest schema | ~~A place to host `registry.json` publicly~~ Solved - see update above |
| Local registry file + 2 real example entries | A registry-repo PR workflow + CI wiring |
| `setu marketplace validate` CLI command | A dashboard UI to browse/install listed plugins |
| Subprocess-sandboxed plugin execution (`apps/gateway/plugins/sandbox.py`) | An actual "install a marketplace plugin" pipeline for the sandbox to run |
| This design doc | Reviewer capacity (see Governance) to actually review submissions |
