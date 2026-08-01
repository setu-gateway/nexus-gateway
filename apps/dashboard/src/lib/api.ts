const BASE_URL = import.meta.env.VITE_GATEWAY_URL ?? "/api";

async function request<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export interface ProviderBreakdown {
  provider: string;
  requests: number;
  errors: number;
  avg_latency_ms: number;
  total_cost: number;
}

export interface AnalyticsSummary {
  total_requests: number;
  successful_requests: number;
  failed_requests: number;
  error_rate: number;
  avg_latency_ms: number;
  total_estimated_cost: number;
  total_tokens: number;
  cache_hit_rate: number;
  fallback_rate: number;
  by_provider: ProviderBreakdown[];
}

export interface RequestLog {
  id: string;
  request_id: string;
  organization_id: string | null;
  requested_model: string;
  selected_provider: string | null;
  routing_policy: string | null;
  fallback_used: boolean;
  rule_applied: string | null;
  status: "success" | "error";
  error_message: string | null;
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  estimated_cost: number;
  cache_hit: boolean;
  latency_ms: number;
  timeline: Record<string, number> | null;
  created_at: string;
}

export interface ProviderDetail {
  name: string;
  provider_name: string;
  enabled: boolean;
  capabilities: Record<string, boolean>;
  models: string[];
}

export interface ProviderMetrics {
  provider_name: string;
  status: "online" | "degraded" | "offline";
  trust_score: number;
  latency_ms: number | null;
  success_rate: number;
  error_rate: number;
  total_requests: number;
  total_errors: number;
  is_rate_limited: boolean;
  last_successful_request: string | null;
}

export interface ModelInfo {
  id: string;
  object: string;
  owned_by: string;
  root: string;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  plan: string;
  created_at: string;
  updated_at: string;
}

export interface Project {
  id: string;
  name: string;
  organization_id: string;
  description: string | null;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  project_id: string;
  masked_key: string;
  last_used_at: string | null;
  expires_at: string | null;
  created_at: string;
}

export const api = {
  analyticsSummary: () => request<AnalyticsSummary>("/analytics/summary"),
  requestLogs: (params: { status?: string; provider?: string; organization_id?: string } = {}) => {
    const qs = new URLSearchParams(params as Record<string, string>).toString();
    return request<RequestLog[]>(`/analytics/requests${qs ? `?${qs}` : ""}`);
  },
  providers: () => request<ProviderDetail[]>("/providers"),
  providerMetrics: () => request<ProviderMetrics[]>("/providers/metrics/all"),
  models: () => request<{ object: string; data: ModelInfo[] }>("/v1/models"),
  organizations: () => request<Organization[]>("/organizations"),
  projects: (organizationId?: string) =>
    request<Project[]>(`/projects${organizationId ? `?organization_id=${organizationId}` : ""}`),
  apiKeys: (projectId?: string) => request<ApiKey[]>(`/keys${projectId ? `?project_id=${projectId}` : ""}`),
};
