# Launch Readiness Review

A self-audit performed as if by an external developer encountering this repository
for the first time, per the checklist the [Sprint 7 ecosystem
build-out](CHANGELOG.md) plan called for before any public launch post. Honest
findings, not a rubber stamp - a review that finds nothing wrong isn't a review.

**Verdict: not ready for a broad public announcement yet**, though the two largest
gaps this review originally flagged - docs-site integration and CI vulnerability
scanning for the new SDKs - are now closed (see the "Update" notes below). Core
platform (v0.1.0-alpha) is solid and genuinely verified, and most of what shipped in
this pass is real, working, and tested - but the marketplace still has no live,
publicly-hosted registry or install pipeline, and a few smaller gaps below remain.
Consistent with [GROWTH.md](GROWTH.md)'s own advice: let real users find sharp edges
gradually, don't invite a crowd to find them all at once.

## Repository structure

**Good**: clear separation (`apps/`, `packages/`, `plugins/`, `infrastructure/`,
`rfcs/`, `tests/`). RFCs document real architectural decisions, not after-the-fact
rationalization.

**Gap**: this pass added Go, Rust, Java, and C# toolchains alongside the existing
Python/TypeScript/Node stack - six language ecosystems in one repository now. That's
a real onboarding cost. A first-time contributor fixing a docs typo shouldn't need
to wonder whether they need Maven installed. See "First-time contributor experience"
below.

## README

Accurate as of this pass (license badge, project structure table, and Quickstart
all updated alongside the code they describe). Quickstart still only mentions the
gateway + dashboard + Postgres + Redis - it doesn't mention the website, the new
SDKs, or the Terraform/Helm/Operator paths, which is *correct* for a quickstart
(those aren't day-one concerns) but means a reader has to already know to look in
`apps/website`, `packages/sdk-*`, and `infrastructure/` to find them.

## Documentation (Mintlify site)

**Update since this review was first written**: closed. The Policy Engine, Cost
Optimizer, Traffic Replay, Terraform provider, Helm chart, Kubernetes Operator,
Plugin Marketplace, Provider Certification, and the four new SDKs (Go, Rust, Java,
C#) each now have a real `.mdx` page wired into `docs.json`'s navigation - not just
a package README. Verified with `mint validate` (clean) and by loading the pages in
a live `mint dev` preview, not just by editing `docs.json` and assuming it worked.
Fixing this also surfaced a real, separate gap in `.mintignore`: `apps/website/` and
the Helm chart's Go-template YAML were never excluded, so `mint validate` was
already silently broken for anyone who ran it after Epics 7.1/7.7 landed, before
this pass - both are now excluded for the same reason `apps/dashboard/` already was.

## Landing page

`apps/website` is real, builds cleanly, and was verified rendering correctly in a
browser end-to-end. **Update since this review was first written**: it's now
deployment-ready, not just buildable - a Dockerfile (`infrastructure/docker/Dockerfile.website`)
was built and smoke-tested serving the real production build, and
[`DEPLOYMENT_RUNBOOK.md`](DEPLOYMENT_RUNBOOK.md) walks through both a managed-static-host
path and a self-hosted path with automatic HTTPS. Still not deployed anywhere
publicly - that step needs a hosting account and a domain, both of which are your
decision to make, not something this pass could do for you. The existing Mintlify
docs site's `index.mdx` also still functions as a de facto landing page and hasn't
been reconciled with the new dedicated site;
decide which one is canonical before pointing a domain at either.

## API design

RESTful, OpenAPI-schema'd via FastAPI, consistent tenant-isolation pattern
(`owns_organization()` + 404-not-403 for cross-tenant access) applied uniformly
across every dashboard-management router, including the new Policies router. Real
bug found and fixed *during this pass*: `/v1/models` and `/analytics/*` rejected a
dashboard session JWT as an invalid API key (two different, non-interchangeable
auth mechanisms colliding on the same endpoint) - fixed centrally in
`apps/gateway/auth/context.py`. Worth noting precisely because it shipped broken
initially and was only caught by live browser verification, not by static review or
the existing test suite - a reminder that this class of bug doesn't show up any
other way.

## Security

Real progress: RBAC + tenant isolation now cover every dashboard-management
endpoint (this was a genuine, previously-unauthenticated gap closed earlier in this
project's history). The Enterprise Policy Engine adds real guardrails (provider
allow/denylist, context-window floor, secret-pattern blocking), enforced before
routing, not just logged after the fact.

**Update since this review was first written**: plugin execution now has a real
subprocess sandbox (`apps/gateway/plugins/sandbox.py`) - wall-clock timeout,
CPU-time limit, and a memory ceiling on Linux, tested against real misbehaving
plugins (infinite loop, memory bomb, a crashing plugin) plus the real bundled
`hello_world` plugin. It is **not yet wired to anything**, because there is still
no live "install a marketplace plugin" pipeline for it to sandbox - see
`marketplace/DESIGN.md`'s update for the precise scope of what this does and
doesn't close.

**Update since this review was first written**: CI dependency-vulnerability scanning
now covers all four new language ecosystems too - `govulncheck` (Go), `cargo audit`
(Rust), `dotnet list package --vulnerable` with custom fail-on-match logic (C#), and
OWASP dependency-check (Java, needs a maintainer-supplied `NVD_API_KEY` secret for
full effect), plus a PR-diff-wide `dependency-review-action` job. This wasn't just a
paperwork exercise: running `govulncheck` for the first time found real, exploitable
CVEs already present in the Terraform provider's and Kubernetes Operator's
transitive dependencies (`grpc`, `golang.org/x/text`, `golang.org/x/net`), fixed via
dependency upgrades and re-verified.

**Real, named gaps**:
- No Prometheus `/metrics` endpoint exists yet, despite the Helm chart shipping a
  (deliberately inert, clearly labeled) `ServiceMonitor` for one.

## Performance

Real, honestly-reported benchmark data in `PERFORMANCE.md`, including a connection-
pool-exhaustion bug found under concurrency and the fix applied for it. Not
re-benchmarked since the fix (documented as a known follow-up in that file already).

## Docker / Kubernetes experience

Docker Compose is solid and was extensively live-verified this session, including a
dev-mode hot-reload override. The Helm chart passes `helm lint` and renders
correctly under every combination of its feature toggles. The Kubernetes Operator
is genuinely unusual for a project at this stage in that it was actually
cluster-tested (a real local `kind` cluster, not just compiled) - auto-upgrade,
scaling, and live secret-rotation were all observed working, and two real bugs
(`imagePullPolicy` defaulting to `Always`, and a missing Secret watch) were caught
and fixed by that testing rather than shipped silently broken.

**Gap**: none of this - Helm chart, Operator, or the SDK build artifacts - has CI
coverage. `docker-build` in `ci.yml` only builds the gateway/dashboard images.

## Installation from scratch

`docker compose up -d` → real, working gateway + dashboard, verified repeatedly
this session. From-source install (`contributing/development.mdx`) remains accurate
for the core platform. Installing any of the *new* SDKs or tools requires reading
that specific package's README - there's no single "install everything" path, which
is probably correct (nobody needs all six language SDKs at once) but should be
stated explicitly somewhere so it doesn't read as an oversight.

## First-time contributor experience

`CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `GOVERNANCE.md`, `MAINTAINERS.md`, issue
and PR templates all exist and are accurate. `GOVERNANCE.md`/`MAINTAINERS.md` are
honest about being a single-maintainer project today rather than inventing a team.

**Gap**: `contributing/development.mdx` predates this pass and only documents the
Python/Node workflow - it doesn't mention the Go/Rust/Java/C# toolchains needed to
touch the new SDKs, Terraform provider, or Operator. A contributor touching only
the gateway or dashboard is unaffected; anyone touching the new ecosystem work has
to reverse-engineer the toolchain from each package's own README.

## Before the next launch post

1. ~~Wire the Sprint 7 features into the Mintlify docs site navigation.~~ Done.
2. ~~Add dependency-vulnerability scanning for Go/Rust/Java/C# to CI.~~ Done.
3. Extend `contributing/development.mdx` with a per-ecosystem toolchain section.
4. Decide (and act on) whether `apps/website` or the existing Mintlify `index.mdx`
   is the canonical landing page.
5. Re-run `PERFORMANCE.md`'s benchmark to confirm the connection-pool fix under load.

Still in priority order - 3 is the next most valuable (a contributor bouncing off an
undocumented toolchain requirement is a worse first impression than a missing
benchmark re-run), but none of these three block a launch post the way 1 and 2 did.
