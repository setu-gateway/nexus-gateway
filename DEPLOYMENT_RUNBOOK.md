# Deployment Runbook: Website, Playground, Marketplace

Everything in this file is built and verified - Dockerfiles built successfully,
containers started and served real traffic during this pass, and
`docker compose config` / `caddy validate` confirmed the compose overlay and
Caddyfile are both syntactically and semantically correct. What it deliberately
does **not** do is create a hosting account, register a domain, or enter any
payment/billing information on your behalf - those are steps only you can take, and
each section below says exactly where that step falls in the sequence.

## Prerequisites (all three sections need these)

- A server/VM/container platform you already have access to (a $5-10/mo VPS is
  enough for all three services combined at low traffic), **or** a managed static
  host account for the website specifically (see below - it doesn't need a VPS at
  all).
- A domain name you own, with the ability to edit its DNS records.
- Docker + Docker Compose on whatever host runs the containers.

Nothing below picks a specific provider for you (DigitalOcean vs. Hetzner vs. AWS
Lightsail vs. your own hardware are all equivalent from this repo's point of view) -
that choice, and creating the account for it, is yours to make.

## 1. Website (`apps/website`)

The website is a fully static build - no server-side code, no API calls (verified:
`apps/website/src` has zero `fetch`/API references). This means it has the simplest
possible deployment story of the three:

**Option A - a managed static host (simplest, no server to manage):**
Point Netlify, Vercel, Cloudflare Pages, or GitHub Pages at this repo with:
- Build command: `pnpm --filter @setu/website build`
- Output directory: `apps/website/dist`

Each of those has its own free tier and its own account-creation step - pick one and
sign up; nothing here needs to know which.

**Option B - self-host via Docker (if you'd rather run it on your own VPS):**

```bash
docker build -f infrastructure/docker/Dockerfile.website -t setu-website .
docker run -d -p 3001:3001 --name setu-website --restart unless-stopped setu-website
```

Or via compose (already wired into `docker-compose.yml`):

```bash
docker compose up -d website
```

Either way, point your domain's DNS `A`/`CNAME` record at wherever it ends up
running - a managed host's own dashboard tells you what to point at; for
self-hosting, see the Caddy setup in step 2, which can front this the same way it
fronts the gateway and dashboard.

## 2. Playground (public gateway access)

The playground (`GET /playground`, `POST /playground/completion`) is already part of
the gateway container - there's no separate build for it. "Exposing it publicly"
means putting a domain and TLS in front of the gateway container you're likely
already running via `docker compose up`. It's already rate-limited server-side (10
requests/minute per IP - see [features/rate-limiting](features/rate-limiting.mdx)
and `apps/gateway/api/playground_api.py`) specifically so this is safe to do without
further application changes.

1. Point your domain's DNS `A` record at your server's public IP. This is the one
   step that requires you to already own the domain from the prerequisites above.
2. Copy the example reverse-proxy config and fill in your real domain(s):
   ```bash
   cp infrastructure/docker/Caddyfile.example infrastructure/docker/Caddyfile
   # edit infrastructure/docker/Caddyfile: replace playground.your-domain.com and
   # app.your-domain.com with your actual domains
   ```
3. Open ports 80 and 443 on your host/cloud firewall (needed for both normal HTTPS
   traffic and Let's Encrypt's automatic certificate issuance).
4. Bring everything up with the production overlay:
   ```bash
   docker compose -f docker-compose.yml -f infrastructure/docker/docker-compose.production.yml up -d
   ```
   Caddy requests and renews its own TLS certificate automatically on first
   request to each domain - no separate certbot step.
5. Firewall off direct access to ports 8000 (gateway) and 3000 (dashboard) at the
   host/cloud level once Caddy is confirmed working, so Caddy is the only public
   entry point. This compose setup doesn't remove those `ports:` mappings for you
   (overlay files replace list-type keys entirely rather than merging them, which
   is easy to get subtly wrong) - a host firewall rule is a more reliable way to
   close them than fighting compose's merge semantics.

Exposing the *whole* gateway (not just `/playground`) publicly this way is a
legitimate choice too - see [API Authentication](api/authentication.mdx) for what is
and isn't protected on `/v1/*` before doing so.

## 3. Marketplace registry (`marketplace/registry.json`)

**Option A - zero infrastructure (this already works today):** this repository is
already public on GitHub, so `registry.json` and its schema are already fetchable
with no deployment step at all, once a change is committed and pushed to `main`:

```
https://raw.githubusercontent.com/setu-gateway/nexus-gateway/main/marketplace/registry.json
https://raw.githubusercontent.com/setu-gateway/nexus-gateway/main/marketplace/schema/plugin-manifest.schema.json
```

This is genuinely sufficient for `setu marketplace validate` or any tool that just
needs to fetch the registry - it needs no new account, no new domain, and no new
container. The real remaining gap (see
[`marketplace/DESIGN.md`](marketplace/DESIGN.md)) is the *submission workflow* -
who reviews and merges a third-party PR to this file - which is a process/governance
question, not a hosting one.

**Option B - self-hosted, independent of GitHub** (if you want it under your own
domain, e.g. for a custom `setu marketplace validate --registry-url` target later):

```bash
docker build -f infrastructure/docker/Dockerfile.marketplace -t setu-marketplace .
docker run -d -p 3002:3002 --name setu-marketplace --restart unless-stopped setu-marketplace
```

Serves `registry.json` and `schema/` with `application/json` and open CORS (verified
via `curl` during this pass) - suitable for any client to fetch directly.

## What's still a real decision, not just a missing step

- **Which host/provider** for the VPS (if you go that route) or the static host (for
  the website) - genuinely your call, not something this repo can pick for you.
- **The marketplace's submission/review workflow** - hosting the JSON file (this
  runbook) is solved; deciding who reviews a stranger's PR to it is not, and doesn't
  have a technical fix.
- **`apps/website` vs. the existing Mintlify `index.mdx`** as the canonical landing
  page - both exist today and haven't been reconciled (see `LAUNCH_READINESS.md`).
