// REST-Client mit Bearer-Token (Task 2.1). Nicht-live Daten (Listen, Suche) laufen über React Query,
// alles Live über den Sync-Store (sync/store.ts).
import { create } from "zustand";
import type {
  DocumentOut, Notification, RunListItem, RunStatusView, TaskDetail, TaskListItem, Workflow,
} from "./index";
import type { components } from "./types";

type S = components["schemas"];
export type UserOut = S["UserOut"];
export type TokenResponse = S["TokenResponse"];
export type DocumentSummary = S["DocumentSummary"];
export type TableSummary = S["TableSummary"];
export type WorkflowSummary = S["WorkflowSummary"];
export type SearchResponse = S["SearchResponse"];
export type SearchHit = S["SearchHit"];
export type RoleOut = S["RoleOut"];
export type SignupRequest = S["SignupRequest"];

const STORAGE_KEY = "dock.auth";

type AuthState = {
  token: string | null;
  user: UserOut | null;
  setAuth: (r: TokenResponse) => void;
  setUser: (u: UserOut) => void;
  logout: () => void;
};

function loadAuth(): { token: string | null; user: UserOut | null } {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch {
    /* privater Modus o. Ä. */
  }
  return { token: null, user: null };
}

function saveAuth(token: string | null, user: UserOut | null) {
  try {
    if (token) localStorage.setItem(STORAGE_KEY, JSON.stringify({ token, user }));
    else localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignorieren */
  }
}

export const useAuth = create<AuthState>((set, get) => ({
  ...loadAuth(),
  setAuth: (r) => {
    saveAuth(r.access_token, r.user);
    set({ token: r.access_token, user: r.user });
  },
  setUser: (u) => {
    saveAuth(get().token, u);
    set({ user: u });
  },
  logout: () => {
    saveAuth(null, null);
    set({ token: null, user: null });
  },
}));

export const hasRole = (user: UserOut | null, role: string) => !!user?.roles.includes(role);
/** Demo-Vereinfachung (Plan, Rechte): Struktur ändern darf nur `einkauf`. */
export const canEditStructure = (user: UserOut | null) => hasRole(user, "einkauf");
/** Freie Dokumente (ohne Workflow-Besitzer) darf jede Rolle anlegen und bearbeiten, Schritt-Dokumente nur `einkauf`. */
export const canEditDocument = (user: UserOut | null, owner?: unknown) => !!user && (!owner || canEditStructure(user));

export class ApiRequestError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object") {
    const b = body as Record<string, unknown>;
    if (typeof b.detail === "string") return b.detail;
    if (Array.isArray(b.detail)) return b.detail.map((d: { msg?: string }) => d.msg).join("; ");
    const err = b.error as { message?: string } | undefined;
    if (err?.message) return err.message;
  }
  return `Anfrage fehlgeschlagen (${status})`;
}

export async function api<T>(path: string, init: RequestInit & { json?: unknown } = {}): Promise<T> {
  const { json, headers, ...rest } = init;
  const token = useAuth.getState().token;
  const res = await fetch(path, {
    ...rest,
    headers: {
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const text = await res.text();
  const body = text ? safeJson(text) : null;
  if (res.status === 401 && token) useAuth.getState().logout();
  if (!res.ok) throw new ApiRequestError(res.status, messageFrom(body, res.status), body);
  return body as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return text;
  }
}

export const authApi = {
  login: (email: string, password: string) =>
    api<TokenResponse>("/api/auth/login", { method: "POST", json: { email, password } }),
  signup: (body: SignupRequest) => api<TokenResponse>("/api/auth/signup", { method: "POST", json: body }),
  me: () => api<UserOut>("/api/me"),
  users: () => api<UserOut[]>("/api/users"),
};

export const listApi = {
  documents: () => api<DocumentSummary[]>("/api/documents"),
  tables: () => api<TableSummary[]>("/api/tables"),
  workflows: () => api<WorkflowSummary[]>("/api/workflows"),
  search: (q: string) => api<SearchResponse>(`/api/search?q=${encodeURIComponent(q)}&limit=8`),
};

function qs(params: Record<string, string | boolean | undefined>): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== "") sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

export const workflowApi = {
  tasks: (params: { status?: string; workflow?: string } = {}) =>
    api<TaskListItem[]>(`/api/tasks${qs(params)}`),
  task: (id: string) => api<TaskDetail>(`/api/tasks/${encodeURIComponent(id)}`),
  runs: (params: { workflow?: string; started_by?: "me" | "any"; status?: string } = {}) =>
    api<RunListItem[]>(`/api/runs${qs(params)}`),
  run: (id: string) => api<RunStatusView>(`/api/runs/${encodeURIComponent(id)}`),
  workflow: (id: string) => api<Workflow>(`/api/workflows/${encodeURIComponent(id)}`),
  documentInRun: (docId: string, runId: string) =>
    api<DocumentOut>(`/api/documents/${encodeURIComponent(docId)}?run=${encodeURIComponent(runId)}`),
  notifications: (unread?: boolean) =>
    api<Notification[]>(`/api/notifications${unread ? "?unread=true" : ""}`),
  markNotificationRead: (id: string) =>
    api<Notification>(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),
  deleteNotification: (id: string) =>
    api<null>(`/api/notifications/${encodeURIComponent(id)}`, { method: "DELETE" }),
};
