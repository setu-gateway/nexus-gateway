import { NavLink, Outlet } from "react-router-dom";

const NAV_ITEMS = [
  { to: "/", label: "Overview", end: true },
  { to: "/providers", label: "Providers" },
  { to: "/models", label: "Models" },
  { to: "/requests", label: "Requests" },
  { to: "/latency", label: "Latency" },
  { to: "/errors", label: "Errors" },
  { to: "/organizations", label: "Organizations" },
  { to: "/projects", label: "Projects" },
  { to: "/api-keys", label: "API Keys" },
];

export function Layout() {
  return (
    <div className="flex min-h-screen bg-slate-950 text-slate-100">
      <aside className="w-56 shrink-0 border-r border-slate-800 p-4">
        <div className="mb-6 flex items-center gap-2 px-2">
          <span className="text-lg font-bold text-brand-light">⚡ Setu</span>
          <span className="text-xs text-slate-500">Dashboard</span>
        </div>
        <nav className="flex flex-col gap-1">
          {NAV_ITEMS.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm transition-colors ${
                  isActive ? "bg-brand/20 text-brand-light font-medium" : "text-slate-400 hover:bg-slate-900 hover:text-slate-100"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="flex-1 overflow-x-auto p-6">
        <Outlet />
      </main>
    </div>
  );
}
