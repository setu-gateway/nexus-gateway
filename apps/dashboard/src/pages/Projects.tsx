import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, Table } from "../components/ui";

export function Projects() {
  const { data, isLoading, error } = useQuery({ queryKey: ["projects"], queryFn: () => api.projects() });

  return (
    <div>
      <PageHeader title="Projects" subtitle="Projects grouped under each organization." />
      <QueryState isLoading={isLoading} error={error} isEmpty={(data ?? []).length === 0}>
        <Table head={["Name", "Organization", "Description", "Created"]}>
          {(data ?? []).map((p) => (
            <tr key={p.id}>
              <td className="px-4 py-3 font-medium">{p.name}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{p.organization_id}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{p.description ?? "—"}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{new Date(p.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
