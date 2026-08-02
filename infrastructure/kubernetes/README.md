# Kubernetes Infrastructure (`infrastructure/kubernetes`)

Plain manifests (not a templated Helm chart yet) for running the gateway and dashboard on Kubernetes. See [the deployment docs](/deployment/kubernetes) for the full walkthrough; summary:

```bash
kubectl apply -f configmap.yaml
cp secret.example.yaml secret.yaml   # fill in real values first
kubectl apply -f secret.yaml
kubectl apply -f gateway-deployment.yaml -f gateway-service.yaml
kubectl apply -f dashboard-deployment.yaml -f dashboard-service.yaml
```

These assume externally-managed PostgreSQL and Redis (`DATABASE_URL`/`REDIS_URL` in `secret.yaml`) - they don't stand up Postgres/Redis themselves. `docker-compose.yml`'s `postgres`/`redis` services are for local development only.
