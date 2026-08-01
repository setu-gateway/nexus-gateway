import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../lib/api";
import { PageHeader, QueryState, StatusBadge, Table } from "../components/ui";

export function Requests() {
  const [statusFilter, setStatusFilter] = useState<string>("");
  const { data, isLoading, error } = useQuery({
    queryKey: ["request-logs", statusFilter],
    queryFn: () => api.requestLogs(statusFilter ? { status: statusFilter } : {}),
  });

  return (
    <div>
      <PageHeader title="Requests" subtitle="Per-request routing outcome and stage timeline (Epic 4.7)." />
      <div className="mb-4 flex gap-2">
        {["", "success", "error"].map((s) => (
          <button
            key={s || "all"}
            onClick={() => setStatusFilter(s)}
            className={`rounded-md px-3 py-1.5 text-xs font-medium ${
              statusFilter === s ? "bg-brand/20 text-brand-light" : "bg-slate-900 text-slate-400 hover:text-slate-200"
            }`}
          >
            {s === "" ? "All" : s === "success" ? "Success" : "Errors"}
          </button>
        ))}
      </div>
      <QueryState isLoading={isLoading} error={error} isEmpty={(data ?? []).length === 0} emptyMessage="No requests recorded yet - send a chat completion to see it here.">
        <Table head={["Time", "Model", "Provider", "Status", "Policy", "Fallback", "Latency", "Cost"]}>
          {(data ?? []).map((r) => (
            <tr key={r.id}>
              <td className="px-4 py-3 text-xs text-slate-400">{new Date(r.created_at).toLocaleString()}</td>
              <td className="px-4 py-3 font-mono text-xs">{r.requested_model}</td>
              <td className="px-4 py-3 capitalize">{r.selected_provider ?? "—"}</td>
              <td className="px-4 py-3">
                <StatusBadge status={r.status} />
              </td>
              <td className="px-4 py-3 text-xs text-slate-400">{r.routing_policy ?? "—"}</td>
              <td className="px-4 py-3 text-xs">{r.fallback_used ? "yes" : "no"}</td>
              <td className="px-4 py-3">{r.latency_ms.toFixed(0)} ms</td>
              <td className="px-4 py-3">${r.estimated_cost.toFixed(5)}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
