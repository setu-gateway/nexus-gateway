import type { ReactNode } from "react";

export function PageHeader({ title, subtitle }: { title: string; subtitle?: string }) {
  return (
    <div className="mb-6">
      <h1 className="text-xl font-semibold text-slate-100">{title}</h1>
      {subtitle && <p className="mt-1 text-sm text-slate-400">{subtitle}</p>}
    </div>
  );
}

export function StatCard({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-4">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-100">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-500">{hint}</div>}
    </div>
  );
}

export function Card({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={`rounded-lg border border-slate-800 bg-slate-900/60 ${className}`}>{children}</div>;
}

export function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    online: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    ok: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    success: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    degraded: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    offline: "bg-red-500/15 text-red-400 border-red-500/30",
    error: "bg-red-500/15 text-red-400 border-red-500/30",
  };
  const style = styles[status] ?? "bg-slate-500/15 text-slate-400 border-slate-500/30";
  return <span className={`inline-block rounded-full border px-2 py-0.5 text-xs font-medium ${style}`}>{status}</span>;
}

export function QueryState({
  isLoading,
  error,
  isEmpty,
  emptyMessage = "No data yet.",
  children,
}: {
  isLoading: boolean;
  error: unknown;
  isEmpty?: boolean;
  emptyMessage?: string;
  children: ReactNode;
}) {
  if (isLoading) return <div className="p-6 text-sm text-slate-500">Loading…</div>;
  if (error) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-300">
        Failed to load: {error instanceof Error ? error.message : String(error)}
      </div>
    );
  }
  if (isEmpty) return <div className="p-6 text-sm text-slate-500">{emptyMessage}</div>;
  return <>{children}</>;
}

export function Table({ head, children }: { head: ReactNode[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-800">
      <table className="w-full text-left text-sm">
        <thead className="bg-slate-900/80 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            {head.map((h, i) => (
              <th key={i} className="px-4 py-3 font-medium">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800">{children}</tbody>
      </table>
    </div>
  );
}
