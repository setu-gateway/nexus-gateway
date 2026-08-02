import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { login, register } from "../lib/auth";

export function Login() {
  const navigate = useNavigate();
  const [mode, setMode] = useState<"login" | "register">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [organizationName, setOrganizationName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setIsSubmitting(true);
    try {
      if (mode === "login") {
        await login(email, password);
      } else {
        await register(email, password, organizationName);
      }
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 text-slate-100">
      <div className="w-full max-w-sm rounded-lg border border-slate-800 bg-slate-900/60 p-8">
        <div className="mb-6 flex items-center gap-2">
          <span className="text-lg font-bold text-brand-light">⚡ Setu</span>
          <span className="text-xs text-slate-500">Dashboard</span>
        </div>
        <h1 className="mb-6 text-lg font-semibold">{mode === "login" ? "Sign in" : "Create an account"}</h1>

        <form onSubmit={handleSubmit} className="flex flex-col gap-4">
          <div>
            <label htmlFor="email" className="mb-1 block text-xs uppercase tracking-wide text-slate-500">
              Email
            </label>
            <input
              id="email"
              type="email"
              required
              autoComplete="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-brand focus:outline-none"
            />
          </div>
          <div>
            <label htmlFor="password" className="mb-1 block text-xs uppercase tracking-wide text-slate-500">
              Password
            </label>
            <input
              id="password"
              type="password"
              required
              minLength={8}
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-brand focus:outline-none"
            />
          </div>
          {mode === "register" && (
            <div>
              <label htmlFor="org-name" className="mb-1 block text-xs uppercase tracking-wide text-slate-500">
                Organization name
              </label>
              <input
                id="org-name"
                type="text"
                placeholder="Default Org"
                value={organizationName}
                onChange={(e) => setOrganizationName(e.target.value)}
                className="w-full rounded-md border border-slate-700 bg-slate-950 px-3 py-2 text-sm text-slate-100 focus:border-brand focus:outline-none"
              />
            </div>
          )}

          {error && <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">{error}</div>}

          <button
            type="submit"
            disabled={isSubmitting}
            className="mt-2 rounded-md bg-brand px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-brand-dark disabled:opacity-50"
          >
            {isSubmitting ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          type="button"
          onClick={() => {
            setError(null);
            setMode(mode === "login" ? "register" : "login");
          }}
          className="mt-4 w-full text-center text-xs text-slate-500 hover:text-slate-300"
        >
          {mode === "login" ? "Need an account? Create one" : "Already have an account? Sign in"}
        </button>
      </div>
    </div>
  );
}
