# Performance Benchmarks

Sprint 6 (Release Sprint, v0.1.0-alpha) baseline performance results for `/v1/chat/completions`, run against a live gateway instance backed by real PostgreSQL and Redis (not the SQLite test harness). All requests hit the `openai`/`gpt-4o` route with no provider API key configured, so responses come from the provider adapter's built-in mock path — this isolates gateway-added latency from upstream LLM latency, which is what these numbers measure.

## Methodology

- Tool: `packages/cli/benchmark.py`'s `benchmark_provider()` (the same engine behind `setu benchmark`), driving concurrent `httpx.AsyncClient` requests with bounded concurrency.
- Target: a locally running gateway (`docker compose up`) with PostgreSQL 16 and Redis 7, unauthenticated requests (no API key).
- Repeated identical prompt across all requests, so after the first request populates the cache, the majority of traffic is a cache hit (memory → Redis → Postgres, in that order) rather than a fresh provider call. This is representative of one real workload shape (repeated/templated prompts) but not of an all-unique-prompt workload — treat these as gateway-overhead numbers, not provider-latency numbers.

## Results

| Requests | Concurrency | Success | Error rate | Throughput | Avg latency | P50 | P95 | P99 |
|---|---|---|---|---|---|---|---|---|
| 100 | 20 | 97/100 | 3.0% | 152.5 req/s | 107.7 ms | 38.1 ms | 426.7 ms | 432.2 ms |
| 1,000 | 50 | 208/1,000 | 79.2% | 0.43 req/s | 1,311.3 ms | 189.6 ms | 346.0 ms | 29,924.3 ms |
| 10,000 | 100 | — | — | — | — | — | — | — |

The 10,000-request run was stopped intentionally partway through. The 1,000-request result already isolated the failure mode clearly (below), and continuing would have meant several more minutes of a known, already-diagnosed failure against a shared environment for no new information.

## Finding: database connection pool exhaustion under concurrency

The 1,000-request run's P99 of **29,924 ms** is not noise — it's the exact signature of `apps/gateway/db/engine.py`'s connection pool being exhausted. Every in-flight request holds its DB session open for the full request duration (`get_db_session` commits only after the endpoint returns), so pool capacity is a hard ceiling on concurrent requests, not just a throughput knob. The prior config (`pool_size=10, max_overflow=20` → 30 max connections) meant the 31st+ concurrent request queued for a connection, and `pool_timeout` defaults to 30 seconds — which is exactly what P99 shows: requests that couldn't get a connection waited the full timeout and then failed.

Gateway logs during the run confirmed this directly:

```
sqlalchemy.exc.TimeoutError: QueuePool limit of size 10 overflow 20 reached, connection timed out, timeout 30.00
```

This surfaced two distinct symptoms:
- User-facing request failures (500s propagating from `get_db_session`, and some 503s from the provider-fallback path exhausting `last_error`).
- Silent analytics-recording failures — `record_request()`'s own standalone session lost the same race and logged a warning rather than crashing the request, so some successful responses have no corresponding `request_logs` row under heavy concurrent load.

**Fix applied** (`apps/gateway/db/engine.py`): raised the defaults to `pool_size=20, max_overflow=30` (50 max connections) and made all three pool parameters configurable via `DB_POOL_SIZE` / `DB_MAX_OVERFLOW` / `DB_POOL_TIMEOUT_SECONDS` env vars, documented in `.env.example`. This wasn't verified against a rebuilt container in this pass (the running gateway container was left untouched rather than rebuilding it mid-benchmark) — re-run this benchmark after deploying the change to confirm the P99/error-rate improvement directly.

Container resource usage during the run shows this was a **configuration ceiling, not a hardware ceiling** — there was substantial headroom left:

| Container | Peak CPU | Memory |
|---|---|---|
| gateway | ~27% | ~350 MB |
| postgres | ~32% | ~87 MB |
| redis | — | 1.2 MB, 4 keys |

## Database query pattern (per request, unauthenticated, non-streaming)

Traced from `apps/gateway/api/openai_v1.py`'s request path:

- **Cache hit** (the common case in this benchmark after warmup): ~2 lightweight round-trips — an empty commit after auth resolution, plus `record_request()`'s insert+commit on its own standalone connection. No Postgres read at all (served from in-memory or Redis tier).
- **Cache miss**: adds a `CacheEntry` lookup (`cache/manager.py`'s third cache tier) and, on a non-streaming success, a cache-entry write — roughly 4-5 round-trips total, across two separate connections (the request-scoped session and `record_request`'s standalone one).

The two-connections-per-request pattern (request-scoped + standalone analytics session, both open simultaneously for part of the request) is part of why concurrent load consumes pool capacity faster than a naive "one connection per request" estimate would suggest.

## Recommendations

- Re-run this benchmark after deploying the pool-size fix to confirm the P99/error-rate improvement.
- For deployments expecting sustained high concurrency, consider a connection-pooling proxy (e.g. PgBouncer) in front of Postgres rather than raising `DB_POOL_SIZE` indefinitely — each gateway replica's pool budget is per-instance, and Postgres's own `max_connections` (default 100) is a hard ceiling across all replicas combined.
- The silent analytics-recording failure under pool pressure is a real gap: a burst of concurrent traffic can produce successful responses with incomplete `request_logs` coverage. Worth deciding whether that should escalate to a metric/alert rather than a debug-level log line, if accurate under-load analytics matters for your deployment.
