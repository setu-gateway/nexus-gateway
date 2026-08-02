import { useSyncExternalStore } from "react";

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  organization_id: string | null;
}

interface StoredAuth {
  accessToken: string;
  refreshToken: string;
  user: CurrentUser;
}

const STORAGE_KEY = "setu_auth";
const BASE_URL = import.meta.env.VITE_GATEWAY_URL ?? "/api";
const listeners = new Set<() => void>();

// useSyncExternalStore requires getSnapshot() to return a reference-stable value
// when nothing has changed - a fresh JSON.parse() on every call would return a new
// object each time even if localStorage is untouched, which React interprets as
// "changed every render" and spins into an infinite update loop. cachedAuth/cachedRaw
// make repeated reads of an unchanged value return the *same* object.
let cachedRaw: string | null = null;
let cachedAuth: StoredAuth | null = null;

function read(): StoredAuth | null {
  const raw = localStorage.getItem(STORAGE_KEY);
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    try {
      cachedAuth = raw ? (JSON.parse(raw) as StoredAuth) : null;
    } catch {
      cachedAuth = null;
    }
  }
  return cachedAuth;
}

function write(auth: StoredAuth | null): void {
  if (auth) localStorage.setItem(STORAGE_KEY, JSON.stringify(auth));
  else localStorage.removeItem(STORAGE_KEY);
  cachedRaw = localStorage.getItem(STORAGE_KEY);
  cachedAuth = auth;
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Reactive current-user hook (via useSyncExternalStore) - re-renders whenever auth
 * state changes, including changes made outside React (api.ts clearing auth on a
 * failed token refresh). */
export function useCurrentUser(): CurrentUser | null {
  const auth = useSyncExternalStore(subscribe, read);
  return auth?.user ?? null;
}

export function getAccessToken(): string | null {
  return read()?.accessToken ?? null;
}

async function parseErrorDetail(res: Response): Promise<string> {
  try {
    const body = await res.json();
    return body.detail ?? res.statusText;
  } catch {
    return res.statusText;
  }
}

async function fetchCurrentUser(accessToken: string): Promise<CurrentUser> {
  const res = await fetch(`${BASE_URL}/auth/me`, { headers: { Authorization: `Bearer ${accessToken}` } });
  if (!res.ok) throw new Error("Failed to load current user");
  return res.json();
}

export async function login(email: string, password: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  const { access_token, refresh_token } = await res.json();
  const user = await fetchCurrentUser(access_token);
  write({ accessToken: access_token, refreshToken: refresh_token, user });
}

export async function register(email: string, password: string, organizationName?: string): Promise<void> {
  const res = await fetch(`${BASE_URL}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, organization_name: organizationName || undefined }),
  });
  if (!res.ok) throw new Error(await parseErrorDetail(res));
  await login(email, password);
}

export function logout(): void {
  write(null);
}

/** Used by api.ts's request wrapper on a 401: tries to mint a fresh access token
 * from the stored refresh token, without going through the full login form. Clears
 * auth entirely if the refresh token itself is no longer valid. */
export async function refreshAccessToken(): Promise<string | null> {
  const current = read();
  if (!current) return null;
  try {
    const res = await fetch(`${BASE_URL}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: current.refreshToken }),
    });
    if (!res.ok) {
      write(null);
      return null;
    }
    const { access_token, refresh_token } = await res.json();
    write({ ...current, accessToken: access_token, refreshToken: refresh_token });
    return access_token;
  } catch {
    return null;
  }
}
