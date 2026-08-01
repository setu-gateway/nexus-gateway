import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, Table } from "../components/ui";

export function Errors() {
  const { data, isLoading, error } = useQuery({
    queryKey: ["request-logs", "error"],
    queryFn: () => api.requestLogs({ status: "error" }),
  });

  return (
    <div>
      <PageHeader title="Errors" subtitle="Failed requests, with the routing rule or provider error that caused them." />
      <QueryState isLoading={isLoading} error={error} isEmpty={(data ?? []).length === 0} emptyMessage="No errors recorded. 🎉">
        <Table head={["Time", "Model", "Policy", "Rule applied", "Error"]}>
          {(data ?? []).map((r) => (
            <tr key={r.id}>
              <td className="px-4 py-3 text-xs text-slate-400">{new Date(r.created_at).toLocaleString()}</td>
              <td className="px-4 py-3 font-mono text-xs">{r.requested_model}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{r.routing_policy ?? "—"}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{r.rule_applied ?? "—"}</td>
              <td className="px-4 py-3 text-xs text-red-300">{r.error_message ?? "—"}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
