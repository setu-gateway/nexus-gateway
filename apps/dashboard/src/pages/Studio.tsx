import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type RoutingPolicy } from "../lib/api";
import { Card, PageHeader, QueryState, StatCard } from "../components/ui";

const CONDITION_FIELDS = [
  { value: "latency", label: "Latency", suffix: "ms", operators: [">", "<", ">=", "<="] },
  { value: "provider", label: "Provider status", suffix: "", operators: ["=="] },
  { value: "estimated_cost", label: "Estimated cost", suffix: "", operators: [">", "<"] },
] as const;

const ACTION_TYPES = ["fallback", "use", "reject"] as const;
const ROUTING_POLICIES: RoutingPolicy[] = [
  "highest_availability",
  "lowest_latency",
  "lowest_cost",
  "round_robin",
  "weighted",
  "user_preference",
  "capability_based",
];

export function Studio() {
  const orgsQuery = useQuery({ queryKey: ["organizations"], queryFn: api.organizations });
  const providersQuery = useQuery({ queryKey: ["providers"], queryFn: api.providers });
  const organizationId = orgsQuery.data?.[0]?.id;

  return (
    <div>
      <PageHeader
        title="Gateway Studio"
        subtitle="A visual control plane: build routing rules, simulate a policy against real traffic, and test a prompt across providers side by side - without touching production traffic."
      />
      <QueryState isLoading={orgsQuery.isLoading} error={orgsQuery.error} isEmpty={!organizationId} emptyMessage="Create an organization first.">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <RoutingRuleBuilder organizationId={organizationId!} providerNames={(providersQuery.data ?? []).map((p) => p.provider_name)} />
          <PolicySimulator organizationId={organizationId!} />
        </div>
        <div className="mt-6">
          <PromptTester providerNames={(providersQuery.data ?? []).map((p) => p.provider_name)} />
        </div>
      </QueryState>
    </div>
  );
}

function RoutingRuleBuilder({ organizationId, providerNames }: { organizationId: string; providerNames: string[] }) {
  const queryClient = useQueryClient();
  const rulesQuery = useQuery({ queryKey: ["routing-rules", organizationId], queryFn: () => api.routingRules(organizationId) });

  const [name, setName] = useState("");
  const [field, setField] = useState<(typeof CONDITION_FIELDS)[number]["value"]>("latency");
  const [operator, setOperator] = useState(">");
  const [value, setValue] = useState("500");
  const [actionType, setActionType] = useState<(typeof ACTION_TYPES)[number]>("fallback");
  const [actionProvider, setActionProvider] = useState(providerNames[0] ?? "");

  const fieldDef = CONDITION_FIELDS.find((f) => f.value === field)!;
  const conditionExpression = `${field} ${operator} ${value}${fieldDef.suffix}`;

  const createMutation = useMutation({
    mutationFn: () =>
      api.createRoutingRule({
        organization_id: organizationId,
        name: name || conditionExpression,
        condition_expression: conditionExpression,
        action_type: actionType,
        action_provider: actionType === "reject" ? undefined : actionProvider,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["routing-rules", organizationId] });
      setName("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api.deleteRoutingRule(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["routing-rules", organizationId] }),
  });

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-medium text-slate-300">Routing rule builder</h2>
      <div className="flex flex-col gap-3">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Rule name (optional)"
          className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
        />
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">If</span>
          <select value={field} onChange={(e) => setField(e.target.value as typeof field)} className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5">
            {CONDITION_FIELDS.map((f) => (
              <option key={f.value} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
          <select value={operator} onChange={(e) => setOperator(e.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5">
            {fieldDef.operators.map((op) => (
              <option key={op} value={op}>
                {op}
              </option>
            ))}
          </select>
          <input
            value={value}
            onChange={(e) => setValue(e.target.value)}
            className="w-24 rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5"
          />
        </div>
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <span className="text-slate-500">then</span>
          <select value={actionType} onChange={(e) => setActionType(e.target.value as typeof actionType)} className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5">
            {ACTION_TYPES.map((a) => (
              <option key={a} value={a}>
                {a}
              </option>
            ))}
          </select>
          {actionType !== "reject" && (
            <select value={actionProvider} onChange={(e) => setActionProvider(e.target.value)} className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5">
              {providerNames.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
          )}
        </div>
        <button
          onClick={() => createMutation.mutate()}
          disabled={createMutation.isPending}
          className="self-start rounded-md bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {createMutation.isPending ? "Adding…" : "Add rule"}
        </button>
        {createMutation.isError && (
          <div className="text-xs text-red-400">{createMutation.error instanceof Error ? createMutation.error.message : "Failed to add rule"}</div>
        )}
      </div>

      <div className="mt-4 border-t border-slate-800 pt-3">
        <QueryState isLoading={rulesQuery.isLoading} error={rulesQuery.error} isEmpty={(rulesQuery.data ?? []).length === 0} emptyMessage="No routing rules yet.">
          <ul className="flex flex-col gap-2">
            {(rulesQuery.data ?? []).map((rule) => (
              <li key={rule.id} className="flex items-center justify-between rounded-md border border-slate-800 px-3 py-2 text-xs">
                <span>
                  <span className="text-slate-500">if</span> {rule.condition_expression} <span className="text-slate-500">then</span>{" "}
                  {rule.action_type}
                  {rule.action_provider ? ` → ${rule.action_provider}` : ""}
                </span>
                <button onClick={() => deleteMutation.mutate(rule.id)} className="text-slate-500 hover:text-red-400">
                  Remove
                </button>
              </li>
            ))}
          </ul>
        </QueryState>
      </div>
    </Card>
  );
}

function PolicySimulator({ organizationId }: { organizationId: string }) {
  const [policy, setPolicy] = useState<RoutingPolicy>("highest_availability");

  const simulateMutation = useMutation({
    mutationFn: () => api.simulateRoutingPolicy({ policy, organization_id: organizationId }),
  });

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-medium text-slate-300">Policy simulator</h2>
      <p className="mb-3 text-xs text-slate-500">Preview how a policy would distribute your organization's recent traffic - doesn't touch production.</p>
      <div className="flex items-center gap-2">
        <select value={policy} onChange={(e) => setPolicy(e.target.value as RoutingPolicy)} className="rounded-md border border-slate-700 bg-slate-950 px-2 py-1.5 text-sm">
          {ROUTING_POLICIES.map((p) => (
            <option key={p} value={p}>
              {p.replace(/_/g, " ")}
            </option>
          ))}
        </select>
        <button
          onClick={() => simulateMutation.mutate()}
          disabled={simulateMutation.isPending}
          className="rounded-md bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
        >
          {simulateMutation.isPending ? "Simulating…" : "Simulate"}
        </button>
      </div>

      {simulateMutation.isError && (
        <div className="mt-3 text-xs text-red-400">
          {simulateMutation.error instanceof Error ? simulateMutation.error.message : "Simulation failed"}
        </div>
      )}

      {simulateMutation.data && (
        <div className="mt-4">
          <div className="grid grid-cols-3 gap-2">
            <StatCard label="Avg latency" value={`${simulateMutation.data.avg_latency_ms.toFixed(0)}ms`} />
            <StatCard label="Avg cost" value={`$${simulateMutation.data.avg_estimated_cost.toFixed(4)}`} />
            <StatCard label="Fallback rate" value={`${simulateMutation.data.fallback_rate.toFixed(1)}%`} />
          </div>
          <div className="mt-3">
            <div className="mb-1 text-xs uppercase tracking-wide text-slate-500">Provider distribution</div>
            {/* provider_distribution/fallback_rate are already 0-100 percentages
                (apps/gateway/routing/simulator.py), not 0-1 fractions - no *100 here. */}
            {Object.entries(simulateMutation.data.provider_distribution).map(([provider, share]) => (
              <div key={provider} className="mb-1 flex items-center gap-2 text-xs">
                <span className="w-20 capitalize text-slate-400">{provider}</span>
                <div className="h-2 flex-1 rounded-full bg-slate-800">
                  <div className="h-2 rounded-full bg-brand" style={{ width: `${share}%` }} />
                </div>
                <span className="w-12 text-right text-slate-500">{share.toFixed(0)}%</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

function PromptTester({ providerNames }: { providerNames: string[] }) {
  const [prompt, setPrompt] = useState("Summarize what an AI gateway does in one sentence.");
  const [selectedProviders, setSelectedProviders] = useState<string[]>([]);

  const replayMutation = useMutation({
    mutationFn: () =>
      api.replayPrompt({
        messages: [{ role: "user", content: prompt }],
        providers: selectedProviders.length > 0 ? selectedProviders : undefined,
        model: selectedProviders.length === 0 ? "gpt-4o" : undefined,
      }),
  });

  function toggleProvider(name: string) {
    setSelectedProviders((prev) => (prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]));
  }

  return (
    <Card className="p-4">
      <h2 className="mb-3 text-sm font-medium text-slate-300">Test a prompt across providers</h2>
      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={2}
        className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm"
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {providerNames.map((name) => (
          <button
            key={name}
            onClick={() => toggleProvider(name)}
            className={`rounded-full border px-3 py-1 text-xs capitalize ${
              selectedProviders.includes(name) ? "border-brand bg-brand/20 text-brand-light" : "border-slate-700 text-slate-400"
            }`}
          >
            {name}
          </button>
        ))}
      </div>
      <button
        onClick={() => replayMutation.mutate()}
        disabled={replayMutation.isPending}
        className="mt-3 rounded-md bg-brand px-3 py-2 text-sm font-medium text-white hover:bg-brand-dark disabled:opacity-50"
      >
        {replayMutation.isPending ? "Running…" : "Run"}
      </button>

      {replayMutation.isError && (
        <div className="mt-3 text-xs text-red-400">{replayMutation.error instanceof Error ? replayMutation.error.message : "Test failed"}</div>
      )}

      {replayMutation.data && (
        <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-2">
          {replayMutation.data.results.map((r) => (
            <div key={r.provider} className="rounded-md border border-slate-800 p-3 text-xs">
              <div className="mb-1 flex items-center justify-between">
                <span className="font-medium capitalize text-slate-200">{r.provider}</span>
                <span className="text-slate-500">{r.latency_ms.toFixed(0)}ms</span>
              </div>
              {r.success ? (
                <p className="text-slate-400">
                  {(r.response?.choices as { message?: { content?: string } }[] | undefined)?.[0]?.message?.content ??
                    JSON.stringify(r.response)}
                </p>
              ) : (
                <p className="text-red-400">{r.error}</p>
              )}
            </div>
          ))}
        </div>
      )}
    </Card>
  );
}
