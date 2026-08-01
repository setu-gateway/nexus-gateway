import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { Card, PageHeader, QueryState, StatCard } from "../components/ui";

export function Latency() {
  const { data, isLoading, error } = useQuery({ queryKey: ["analytics-summary"], queryFn: api.analyticsSummary });

  const maxLatency = Math.max(1, ...((data?.by_provider ?? []).map((p) => p.avg_latency_ms)));

  return (
    <div>
      <PageHeader title="Latency" subtitle="Average latency per provider, from recorded request history." />
      <QueryState isLoading={isLoading} error={error}>
        {data && (
          <>
            <div className="mb-6">
              <StatCard label="Gateway-wide average" value={`${data.avg_latency_ms.toFixed(0)} ms`} hint={`across ${data.total_requests} requests`} />
            </div>
            <Card className="p-4">
              {data.by_provider.length === 0 ? (
                <p className="text-sm text-slate-500">No data yet.</p>
              ) : (
                <div className="flex flex-col gap-3">
                  {data.by_provider.map((p) => (
                    <div key={p.provider}>
                      <div className="mb-1 flex justify-between text-xs text-slate-400">
                        <span className="capitalize">{p.provider}</span>
                        <span>{p.avg_latency_ms.toFixed(0)} ms</span>
                      </div>
                      <div className="h-2 w-full overflow-hidden rounded-full bg-slate-800">
                        <div
                          className="h-full rounded-full bg-brand"
                          style={{ width: `${Math.max(4, (p.avg_latency_ms / maxLatency) * 100)}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )}
      </QueryState>
    </div>
  );
}
