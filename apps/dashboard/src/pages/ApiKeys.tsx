import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, Table } from "../components/ui";

export function ApiKeys() {
  const { data, isLoading, error } = useQuery({ queryKey: ["api-keys"], queryFn: () => api.apiKeys() });

  return (
    <div>
      <PageHeader title="API Keys" subtitle="Scoped keys issued to projects. Plaintext keys are never shown after creation." />
      <QueryState isLoading={isLoading} error={error} isEmpty={(data ?? []).length === 0}>
        <Table head={["Name", "Key", "Project", "Last used", "Expires", "Created"]}>
          {(data ?? []).map((k) => (
            <tr key={k.id}>
              <td className="px-4 py-3 font-medium">{k.name}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{k.masked_key}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{k.project_id}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{k.last_used_at ? new Date(k.last_used_at).toLocaleString() : "never"}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{k.expires_at ? new Date(k.expires_at).toLocaleDateString() : "never"}</td>
              <td className="px-4 py-3 text-xs text-slate-400">{new Date(k.created_at).toLocaleDateString()}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
