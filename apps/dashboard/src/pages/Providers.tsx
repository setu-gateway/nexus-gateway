import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, StatusBadge, Table } from "../components/ui";

export function Providers() {
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const metricsQuery = useQuery({ queryKey: ["provider-metrics"], queryFn: api.providerMetrics });

  const metricsByName = new Map((metricsQuery.data ?? []).map((m) => [m.provider_name, m]));

  return (
    <div>
      <PageHeader title="Providers" subtitle="Registered provider adapters, capabilities, and live trust scores." />
      <QueryState
        isLoading={providersQuery.isLoading || metricsQuery.isLoading}
        error={providersQuery.error || metricsQuery.error}
        isEmpty={(providersQuery.data ?? []).length === 0}
      >
        <Table head={["Provider", "Status", "Trust score", "Enabled", "Capabilities", "Models"]}>
          {(providersQuery.data ?? []).map((p) => {
            const metrics = metricsByName.get(p.provider_name);
            const caps = Object.entries(p.capabilities)
              .filter(([, v]) => v)
              .map(([k]) => k);
            return (
              <tr key={p.provider_name}>
                <td className="px-4 py-3 font-medium capitalize">{p.provider_name}</td>
                <td className="px-4 py-3">{metrics ? <StatusBadge status={metrics.status} /> : "—"}</td>
                <td className="px-4 py-3">{metrics ? metrics.trust_score.toFixed(1) : "—"}</td>
                <td className="px-4 py-3">
                  <StatusBadge status={p.enabled ? "online" : "offline"} />
                </td>
                <td className="px-4 py-3 text-xs text-slate-400">{caps.join(", ") || "—"}</td>
                <td className="px-4 py-3 text-xs text-slate-400">{p.models.length}</td>
              </tr>
            );
          })}
        </Table>
      </QueryState>
    </div>
  );
}
