import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, StatCard, Table } from "../components/ui";

export function Overview() {
  const { data, isLoading, error } = useQuery({ queryKey: ["analytics-summary"], queryFn: api.analyticsSummary });

  return (
    <div>
      <PageHeader title="Overview" subtitle="Gateway-wide request volume, cost, and reliability." />
      <QueryState isLoading={isLoading} error={error}>
        {data && (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <StatCard label="Total requests" value={data.total_requests.toLocaleString()} />
              <StatCard label="Error rate" value={`${data.error_rate.toFixed(1)}%`} hint={`${data.failed_requests} failed`} />
              <StatCard label="Avg latency" value={`${data.avg_latency_ms.toFixed(0)} ms`} />
              <StatCard label="Est. cost" value={`$${data.total_estimated_cost.toFixed(4)}`} hint={`${data.total_tokens.toLocaleString()} tokens`} />
              <StatCard label="Fallback rate" value={`${data.fallback_rate.toFixed(1)}%`} hint="requests served by a non-primary provider" />
              <StatCard label="Cache hit rate" value={`${data.cache_hit_rate.toFixed(1)}%`} />
            </div>

            <h2 className="mb-3 mt-8 text-sm font-medium text-slate-300">By provider</h2>
            <QueryState isLoading={false} error={null} isEmpty={data.by_provider.length === 0}>
              <Table head={["Provider", "Requests", "Errors", "Avg latency", "Total cost"]}>
                {data.by_provider.map((p) => (
                  <tr key={p.provider}>
                    <td className="px-4 py-3 font-medium capitalize">{p.provider}</td>
                    <td className="px-4 py-3">{p.requests}</td>
                    <td className="px-4 py-3">{p.errors}</td>
                    <td className="px-4 py-3">{p.avg_latency_ms.toFixed(0)} ms</td>
                    <td className="px-4 py-3">${p.total_cost.toFixed(4)}</td>
                  </tr>
                ))}
              </Table>
            </QueryState>
          </>
        )}
      </QueryState>
    </div>
  );
}
