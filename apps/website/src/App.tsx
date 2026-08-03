const GITHUB_URL = "https://github.com/setu-gateway/nexus-gateway";
const DOCS_URL = "https://docs.setu-gateway.dev";

const NAV_LINKS = [
  { label: "Features", href: "#features" },
  { label: "Architecture", href: "#architecture" },
  { label: "Providers", href: "#providers" },
  { label: "Benchmarks", href: "#benchmarks" },
  { label: "Docs", href: DOCS_URL },
];

const FEATURES = [
  { title: "Intelligent routing", body: "Capability-aware routing across providers with health-based fallback chains, seven selectable policies (lowest latency, lowest cost, weighted, round-robin, and more), and a visual policy simulator." },
  { title: "Zero-trust security by default", body: "Scoped API keys with per-key permissions, IP allowlists, and model/provider restrictions. Real RBAC on every dashboard-management endpoint, tenant-isolated per organization." },
  { title: "Enterprise Policy Engine", body: "Provider allow/denylists, minimum context-window floors, and secret-pattern scanning that blocks a prompt before it's routed - guardrails, not just observability." },
  { title: "Time Machine & Traffic Replay", body: "Record real requests and replay them against a different provider later - one at a time for debugging, or in bulk across a time window to evaluate a provider switch before committing to it." },
  { title: "AI Cost Optimizer", body: "Recommendations based on your organization's actual recorded usage, not a generic price list - with the trade-off (tier, context window, capability loss) called out for every suggestion." },
  { title: "Tiered caching & analytics", body: "Memory → Redis → Postgres cache tiers, full request-level analytics with per-stage timelines, and usage dashboards for cost, latency, and error rate." },
];

const PROVIDERS = ["OpenAI", "Anthropic", "Gemini", "Groq", "Ollama"];

const BENCHMARK = {
  requests: 100,
  concurrency: 20,
  throughput: "152.5 req/s",
  avgLatency: "107.7 ms",
  p95: "426.7 ms",
};

export function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <header className="border-b border-slate-800">
        <nav className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <a href="#" className="flex items-center gap-2 text-lg font-bold">
            <span>⚡</span>
            <span className="text-brand-light">Setu</span>
            <span className="text-slate-500">Gateway</span>
          </a>
          <div className="hidden gap-6 text-sm text-slate-400 md:flex">
            {NAV_LINKS.map((link) => (
              <a key={link.label} href={link.href} className="hover:text-slate-100">
                {link.label}
              </a>
            ))}
          </div>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="rounded-md border border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-900">
            GitHub
          </a>
        </nav>
      </header>

      <section className="mx-auto max-w-4xl px-6 py-24 text-center">
        <h1 className="text-4xl font-bold tracking-tight md:text-6xl">
          One <span className="text-brand-light">OpenAI-compatible API</span> in front of every LLM
        </h1>
        <p className="mx-auto mt-6 max-w-2xl text-lg text-slate-400">
          Setu (सेतु, "bridge") is an open-source, self-hostable AI gateway with intelligent routing, zero-trust security,
          and observability built in - not bolted on.
        </p>
        <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
          <a href={`${DOCS_URL}/getting-started/quickstart`} className="rounded-md bg-brand px-5 py-3 font-medium text-white hover:bg-brand-dark">
            Get started
          </a>
          <a href="/playground" className="rounded-md border border-slate-700 px-5 py-3 font-medium hover:bg-slate-900">
            Try the playground
          </a>
        </div>
        <pre className="mx-auto mt-10 max-w-xl overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/60 p-4 text-left text-xs text-slate-300">
          {`curl http://localhost:8000/v1/chat/completions \\
  -H "Content-Type: application/json" \\
  -d '{"model":"gpt-4o","messages":[{"role":"user","content":"Hello, Setu!"}]}'`}
        </pre>
      </section>

      <section id="features" className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="mb-10 text-center text-2xl font-semibold">What's actually in the box</h2>
        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {FEATURES.map((f) => (
            <div key={f.title} className="rounded-lg border border-slate-800 bg-slate-900/60 p-5">
              <h3 className="mb-2 font-medium text-brand-light">{f.title}</h3>
              <p className="text-sm text-slate-400">{f.body}</p>
            </div>
          ))}
        </div>
      </section>

      <section id="architecture" className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="mb-6 text-center text-2xl font-semibold">Architecture</h2>
        <p className="mx-auto mb-8 max-w-2xl text-center text-sm text-slate-400">
          Request in → auth resolution → policy check → routing decision → provider call (with fallback) → cache write →
          analytics record → response out. Every stage is traced with per-request timing.
        </p>
        <div className="overflow-x-auto rounded-lg border border-slate-800 bg-slate-900/60 p-6">
          <div className="flex min-w-max items-center justify-center gap-3 text-xs">
            {["Client", "Auth", "Policy Engine", "Router", "Provider", "Cache", "Analytics"].map((stage, i, arr) => (
              <div key={stage} className="flex items-center gap-3">
                <div className="rounded-md border border-slate-700 bg-slate-950 px-3 py-2 font-medium">{stage}</div>
                {i < arr.length - 1 && <span className="text-slate-600">→</span>}
              </div>
            ))}
          </div>
        </div>
        <p className="mt-4 text-center text-sm">
          <a href={`${DOCS_URL}/architecture/overview`} className="text-brand-light hover:underline">
            Full architecture docs →
          </a>
        </p>
      </section>

      <section id="providers" className="mx-auto max-w-6xl px-6 py-16">
        <h2 className="mb-8 text-center text-2xl font-semibold">Provider integrations</h2>
        <div className="flex flex-wrap justify-center gap-4">
          {PROVIDERS.map((p) => (
            <div key={p} className="rounded-lg border border-slate-800 bg-slate-900/60 px-6 py-4 text-center font-medium">
              {p}
            </div>
          ))}
        </div>
        <p className="mt-6 text-center text-sm text-slate-500">
          Every provider ships a deterministic mock response with no API key configured, so you can exercise the full
          request path with zero external accounts. Building your own? See{" "}
          <a href={`${DOCS_URL}/plugins/overview`} className="text-brand-light hover:underline">
            the plugin guide
          </a>{" "}
          and run <code className="rounded bg-slate-900 px-1.5 py-0.5">setu certify</code> against it.
        </p>
      </section>

      <section id="benchmarks" className="mx-auto max-w-4xl px-6 py-16">
        <h2 className="mb-8 text-center text-2xl font-semibold">Benchmarks</h2>
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Stat label="Throughput" value={BENCHMARK.throughput} hint={`${BENCHMARK.requests} req, concurrency ${BENCHMARK.concurrency}`} />
          <Stat label="Avg latency" value={BENCHMARK.avgLatency} />
          <Stat label="P95 latency" value={BENCHMARK.p95} />
        </div>
        <p className="mt-6 text-center text-sm text-slate-500">
          Gateway-added overhead, not provider latency (measured against the mock provider path). We publish the full
          methodology and the failure modes we found along the way -{" "}
          <a href={`${GITHUB_URL}/blob/main/PERFORMANCE.md`} className="text-brand-light hover:underline">
            read the honest numbers
          </a>
          , including a connection-pool exhaustion bug we found and fixed at higher concurrency.
        </p>
      </section>

      <section className="mx-auto max-w-4xl px-6 py-16 text-center">
        <h2 className="mb-6 text-2xl font-semibold">Get involved</h2>
        <div className="flex flex-wrap justify-center gap-4 text-sm">
          <FooterLink href={`${GITHUB_URL}/blob/main/ROADMAP.md`} label="Roadmap" />
          <FooterLink href={`${GITHUB_URL}/blob/main/CONTRIBUTING.md`} label="Contributing" />
          <FooterLink href={`${GITHUB_URL}/discussions`} label="Discussions" />
          <FooterLink href={`${GITHUB_URL}/blob/main/GOVERNANCE.md`} label="Governance" />
          <FooterLink href={DOCS_URL} label="Documentation" />
        </div>
        <p className="mt-8 text-xs text-slate-600">
          Setu Gateway doesn't have paid sponsors yet - if that changes, they'll be listed here, not invented for a launch page.
        </p>
      </section>

      <footer className="border-t border-slate-800 py-8 text-center text-xs text-slate-600">
        Setu Gateway is open source under the{" "}
        <a href={`${GITHUB_URL}/blob/main/LICENSE`} className="hover:text-slate-400">
          Apache License 2.0
        </a>
        .
      </footer>
    </div>
  );
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/60 p-5 text-center">
      <div className="text-xs uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold">{value}</div>
      {hint && <div className="mt-1 text-xs text-slate-600">{hint}</div>}
    </div>
  );
}

function FooterLink({ href, label }: { href: string; label: string }) {
  return (
    <a href={href} target="_blank" rel="noreferrer" className="rounded-md border border-slate-800 px-4 py-2 hover:bg-slate-900">
      {label}
    </a>
  );
}
