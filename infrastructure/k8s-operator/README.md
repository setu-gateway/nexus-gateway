# setu-gateway-operator

A Kubernetes operator for advanced, automated gateway lifecycle management, complementing
the [Helm chart](../helm/setu-gateway) (which most deployments should start with).
Manages a `SetuGateway` custom resource:

```yaml
apiVersion: setu.gateway.io/v1alpha1
kind: SetuGateway
metadata:
  name: production
spec:
  image: ghcr.io/setu-gateway/gateway
  version: v0.2.0    # edit this -> the Deployment's image converges (auto upgrade)
  replicas: 3        # edit this -> the Deployment scales (scaling)
  secretName: gateway-secrets
  port: 8000
```

## Capabilities (Epic 7.8)

- **Auto upgrades** - edit `spec.version`, the managed Deployment's image converges to it.
- **Scaling** - edit `spec.replicas`, the Deployment scales to match.
- **Secret rotation** - the operator watches the Secret named by `spec.secretName`;
  when its contents change, it stamps a content-hash annotation onto the pod
  template, which triggers Kubernetes' normal rolling-restart behavior. No manual
  `kubectl rollout restart` needed.
- **Health recovery visibility** - `status.phase` (`Pending`/`Ready`/`Degraded`) and
  `status.readyReplicas` reflect the *actual* Deployment state, visible via
  `kubectl get setugateway`, not just via a separate `kubectl get pods`.

## Verified

Built and `go vet`-clean:

```bash
go build ./...
go vet ./...
```

All four capabilities above were verified end-to-end against a real local
[kind](https://kind.sigs.k8s.io/) cluster during development - not just compiled:
a `SetuGateway` was created, its Deployment/Service came up with a real pod running
the actual gateway image, `spec.replicas` was patched live and the pod count
followed, and the referenced Secret was rotated live (operator running
continuously, no restart) and the pod rolled automatically. That verification pass
caught and fixed two real bugs: `imagePullPolicy` defaulting to `Always` for a
`latest` tag (ignoring an image already loaded into the cluster), and the Secret
watch not being wired up at all (so a Secret-only change silently did nothing).

Reproduce it yourself:

```bash
kind create cluster --name setu-operator-test
kubectl apply -f config/crd/bases/setu.gateway.io_setugateways.yaml
kind load docker-image <your-gateway-image>:latest --name setu-operator-test
kubectl create secret generic gateway-secrets --from-literal=DATABASE_URL=... --from-literal=REDIS_URL=... --from-literal=JWT_SECRET=...
go run .   # runs the manager against your current kubeconfig context
```

## Regenerating the CRD / deepcopy code

After changing `api/v1alpha1/setugateway_types.go`:

```bash
go run sigs.k8s.io/controller-tools/cmd/controller-gen object:headerFile="" paths="./api/..."
go run sigs.k8s.io/controller-tools/cmd/controller-gen crd paths="./api/..." output:crd:artifacts:config=config/crd/bases
```

## Not yet built

A container image and a real Helm/OLM-based install path for the operator itself
aren't included here - packaging and publishing it is a release/hosting decision,
not something to bundle speculatively before the operator has real users.
