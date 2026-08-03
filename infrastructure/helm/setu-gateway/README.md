# setu-gateway Helm chart

Deploys the Setu Gateway and (optionally) its dashboard to Kubernetes. This chart
does not stand up PostgreSQL or Redis itself - bring your own (a managed service, or
your cluster's own database operator/Helm chart) and point `secrets.data` (or
`secrets.existingSecret`) at them, matching the plain-manifest posture already
documented in [`infrastructure/kubernetes/README.md`](../kubernetes/README.md).

## Install

```bash
helm install setu ./infrastructure/helm/setu-gateway \
  --set gateway.image.repository=ghcr.io/your-org/setu-gateway \
  --set gateway.image.tag=v0.1.0 \
  --set secrets.data.DATABASE_URL="postgresql://..." \
  --set secrets.data.REDIS_URL="redis://..." \
  --set secrets.data.JWT_SECRET="$(openssl rand -hex 32)"
```

Prefer `secrets.existingSecret` over `secrets.data` for anything beyond a first try -
see `values.yaml` and this chart's `NOTES.txt` (shown after install) for why.

## What's in `values.yaml`

| Key | Purpose |
| --- | --- |
| `gateway.autoscaling` / `dashboard.autoscaling` | HorizontalPodAutoscaler on CPU utilization, off by default |
| `ingress` | A single Ingress routing `/api` to the gateway and `/` to the dashboard |
| `persistence` | Optional PVC + volume mount - the gateway is stateless by default; this is for a custom use case, not required |
| `monitoring.serviceMonitor` | Prometheus Operator ServiceMonitor - **the gateway doesn't export `/metrics` yet**, so this is correct-but-inert until it does |
| `secrets` | Either a chart-rendered Secret from `secrets.data`, or `secrets.existingSecret` naming one you manage yourself |

## Verify

```bash
helm lint ./infrastructure/helm/setu-gateway
helm template setu ./infrastructure/helm/setu-gateway
```

## After install

Run migrations - this chart does not run them for you:

```bash
uv run alembic upgrade head
```
