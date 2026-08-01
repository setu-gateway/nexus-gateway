import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, Table } from "../components/ui";

export function Organizations() {
  const { data, isLoading, error } = useQuery({ queryKey: ["organizations"], queryFn: api.organizations });

  return (
    <div>
      <PageHeader title="Organizations" subtitle="Tenants registered with the gateway." />
      <QueryState isLoading={isLoading} error={error} isEmpty={(data ?? []).length === 0}>
        <Table head={["Name", "Slug", "Plan", "Created"]}>
          {(data ?? []).map((o) => (
            <tr key={o.id}>
              <td className="px-4 py-3 font-medium">{o.name}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{o.slug}</td>
              <td className="px-4 py-3 capitalize">{o.plan}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{new Date(o.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
