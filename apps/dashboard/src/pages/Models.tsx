import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import { PageHeader, QueryState, Table } from "../components/ui";

export function Models() {
  const { data, isLoading, error } = useQuery({ queryKey: ["models"], queryFn: api.models });

  return (
    <div>
      <PageHeader title="Models" subtitle="Unified model catalog available through the OpenAI-compatible API." />
      <QueryState isLoading={isLoading} error={error} isEmpty={(data?.data ?? []).length === 0}>
        <Table head={["Model ID", "Owned by", "Upstream model"]}>
          {(data?.data ?? []).map((m) => (
            <tr key={m.id}>
              <td className="px-4 py-3 font-mono text-xs">{m.id}</td>
              <td className="px-4 py-3 capitalize">{m.owned_by}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">{m.root}</td>
            </tr>
          ))}
        </Table>
      </QueryState>
    </div>
  );
}
