# Dashboard Application (`apps/dashboard`)

Operational dashboard (Epic 4.9): Overview, Providers, Models, Requests, Latency, Errors, Organizations, Projects, and API Keys, backed by the gateway's `/analytics/*` and `/providers/*` APIs.

React + TypeScript + Tailwind + TanStack Query + React Router, per [RFC-0001](../../rfcs/RFC-0001.md).

## Development

```bash
pnpm install
pnpm dev
```

The dev server proxies `/api/*` to `$VITE_GATEWAY_URL` (default `http://localhost:8000`), so run the gateway alongside it. Set `VITE_GATEWAY_URL` to point at a different gateway instance.

```bash
pnpm build    # type-check + production build to dist/
pnpm preview  # serve the production build locally
```
