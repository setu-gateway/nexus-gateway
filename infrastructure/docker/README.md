# Docker Configurations (`infrastructure/docker`)

Container definitions for Gateway service, Dashboard application, sidecars, and development stacks.

| File | Builds |
| --- | --- |
| `Dockerfile.gateway` | The gateway API |
| `Dockerfile.dashboard` | The React dashboard (nginx, proxies `/api/` to the gateway) |
| `Dockerfile.website` | The marketing/product site (nginx, fully static) |
| `Dockerfile.marketplace` | A standalone static host for `marketplace/registry.json` - see [`../../marketplace/DESIGN.md`](../../marketplace/DESIGN.md) |
| `Dockerfile.docs` | The Mintlify docs site, in dev mode (see its own `CMD`) |

`docker-compose.production.yml` is an overlay adding a Caddy reverse proxy for public HTTPS in front of the gateway and dashboard - layer it on top of the base `docker-compose.yml`, don't merge it in by hand. See [`../../DEPLOYMENT_RUNBOOK.md`](../../DEPLOYMENT_RUNBOOK.md) for the full walkthrough of taking any of this public.
