// Web api client — a thin shim over the shared @futureroots packages.
//
// All types + formatMoney + REACTION_EMOJI now live in @futureroots/types, and
// the request wrapper + endpoint methods + session/media-token policy live in
// @futureroots/api-client (React-free, DOM-free, so web and the Expo app share
// them). This file wires those to the BROWSER: two Web Storage stores (the
// "stay logged in" localStorage vs default sessionStorage split), the media
// token in localStorage, and the window.location session-timeout redirect —
// preserving the web app's exact prior behavior. Anything DOM-only (the admin
// console API, impersonation "view as", CSV blob download) stays here.

import {
  ApiError,
  createApi,
  type MediaTokenStore,
  type SessionStore,
  type UploadPort,
} from "@futureroots/api-client";
// Types used LOCALLY in this file (the web-only admin interfaces below) need an
// explicit import — `export *` re-exports for consumers but does not bring names
// into local scope.
import type { FundAccountStatus } from "@futureroots/types";

// Re-export the entire shared type surface (types, enums, REACTION_EMOJI,
// formatMoney) so `@/lib/api` remains the single import site it always was.
export * from "@futureroots/types";
// Structured-error helpers come from the client, not the types package.
export { ApiError, isPremiumRequired } from "@futureroots/api-client";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// Testnet uses wallet auth and its own /login flow, so the family-product
// session-timeout redirect is suppressed there.
const IS_TESTNET = process.env.NEXT_PUBLIC_TESTNET === "1";

// The session token lives in EITHER store: localStorage for a "stay logged in"
// (remembered) session that survives browser restarts, sessionStorage for a
// default session that a browser/tab close ends — the real shared-computer
// protection. We also track the token's expiry alongside it so ensureSessionFresh
// can slide the window before it lapses (mirrors the media-token exp tracking).
const TOKEN_KEY = "futureroots_token";
const TOKEN_EXP_KEY = "futureroots_token_exp";

// <img>/<video>/<audio> tags can't send an Authorization header, so media URLs
// must carry a credential in the query string. Instead of the account's session
// JWT it is a short-lived token the API honors ONLY on GET /media/{id}, so a
// leaked media URL exposes at most an hour of read-only media access.
const MEDIA_TOKEN_KEY = "futureroots_media_token";
const MEDIA_TOKEN_EXP_KEY = "futureroots_media_token_exp";

/** The browser session store: sessionStorage (default session) wins over
 * localStorage (remembered), and the session lives in exactly one store. */
const sessionStore: SessionStore = {
  read() {
    if (typeof window === "undefined") return null;
    // sessionStorage (default session) wins over localStorage (remembered): a
    // fresh default login on a shared computer takes precedence.
    const s = sessionStorage.getItem(TOKEN_KEY);
    if (s) {
      const raw = sessionStorage.getItem(TOKEN_EXP_KEY);
      return { token: s, expEpochMs: raw ? Number(raw) : null, remembered: false };
    }
    const l = localStorage.getItem(TOKEN_KEY);
    if (l) {
      const raw = localStorage.getItem(TOKEN_EXP_KEY);
      return { token: l, expEpochMs: raw ? Number(raw) : null, remembered: true };
    }
    return null;
  },
  write(rec) {
    if (typeof window === "undefined") return;
    const primary = rec.remembered ? localStorage : sessionStorage;
    const other = rec.remembered ? sessionStorage : localStorage;
    other.removeItem(TOKEN_KEY);
    other.removeItem(TOKEN_EXP_KEY);
    primary.setItem(TOKEN_KEY, rec.token);
    if (rec.expEpochMs) primary.setItem(TOKEN_EXP_KEY, String(rec.expEpochMs));
    else primary.removeItem(TOKEN_EXP_KEY);
  },
  clear() {
    if (typeof window === "undefined") return;
    sessionStorage.removeItem(TOKEN_KEY);
    sessionStorage.removeItem(TOKEN_EXP_KEY);
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(TOKEN_EXP_KEY);
  },
};

/** The browser media-token store (localStorage). */
const mediaTokenStore: MediaTokenStore = {
  read() {
    if (typeof window === "undefined") return null;
    const token = localStorage.getItem(MEDIA_TOKEN_KEY);
    if (!token) return null;
    const raw = localStorage.getItem(MEDIA_TOKEN_EXP_KEY);
    return { token, expEpochMs: raw ? Number(raw) : 0 };
  },
  write(token, expEpochMs) {
    if (typeof window === "undefined") return;
    localStorage.setItem(MEDIA_TOKEN_KEY, token);
    localStorage.setItem(MEDIA_TOKEN_EXP_KEY, String(expEpochMs));
  },
  clear() {
    if (typeof window === "undefined") return;
    localStorage.removeItem(MEDIA_TOKEN_KEY);
    localStorage.removeItem(MEDIA_TOKEN_EXP_KEY);
  },
};

/** Web media upload: PUT the File where the ticket points. */
const upload: UploadPort<File> = {
  contentType: (file) => file.type,
  put: async (url, file, headers) => {
    const res = await fetch(url, { method: "PUT", headers, body: file });
    if (!res.ok) throw new ApiError(res.status, "Upload failed");
  },
};

/** A 401 on an authenticated call means the session lapsed or was rejected:
 * clear it and send the member to a warm re-login, preserving where they were. */
function handleSessionExpired() {
  sessionStore.clear();
  mediaTokenStore.clear();
  if (typeof window === "undefined" || window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  window.location.replace(`/login?next=${encodeURIComponent(next)}&reason=timeout`);
}

const client = createApi<File>({
  apiUrl: API_URL,
  fetch: (url, init) => fetch(url, init),
  store: sessionStore,
  media: { mode: "media-token", store: mediaTokenStore },
  upload,
  isTestnet: IS_TESTNET,
  onSessionExpired: handleSessionExpired,
});

const request = client.request;

export const api = client.api;

/** URL an <img>/<video> tag can load (tags can't send auth headers). The
 * ?token= credential is the short-lived media-ONLY token — never the session
 * JWT — kept fresh by ensureMediaToken() on every API call. */
export function mediaUrl(mediaId: string): string {
  return client.mediaUrl(mediaId);
}

export function getToken(): string | null {
  return client.getToken();
}

/** Set (or clear) the session token. `remember` picks localStorage (survives
 * restarts) vs sessionStorage (default, ends with the browser session).
 * Clearing wipes both stores. Always clears the cached media token, which
 * belongs to the previous identity (login, logout, impersonation switch). */
export function setToken(token: string | null, opts: { remember?: boolean } = {}) {
  client.setToken(token, opts);
}

/** True when the active session is a "stay logged in" (localStorage) token,
 * which is exempt from the idle timeout. */
export function isRememberedSession(): boolean {
  return client.isRemembered();
}

/** Keep a usable media token cached without a per-image round trip. */
export function ensureMediaToken(): Promise<void> {
  return client.ensureMediaToken();
}

/** Slide the session window on API traffic (no-op while comfortably fresh). */
export function ensureSessionFresh(): void {
  client.ensureSessionFresh();
}

// --- Admin command center (role-gated on the server) ---

export interface AdminOverview {
  users: number;
  admins: number;
  families: number;
  children: number;
  contributors: number;
  contributions: number;
  contributed_cents: number;
  pending_bugs: number;
  recent_signups: { id: string; display_name: string; email: string; role: string; created_at: string }[];
  recent_contributions: AdminContribution[];
}

export interface AdminContribution {
  id: string;
  contributor_id: string | null;
  contributor_name: string;
  child_name: string;
  amount_cents: number;
  refunded_cents: number;
  currency: string;
  status: string;
  provider_payment_id: string | null;
  created_at: string;
}

export interface AdminUserRow {
  id: string;
  display_name: string;
  email: string;
  role: "user" | "admin";
  disabled: boolean;
  family_count: number;
  child_count: number;
  created_at: string;
  last_login_at: string | null;
}

export interface AdminUserDetail {
  id: string;
  display_name: string;
  email: string;
  role: "user" | "admin";
  disabled: boolean;
  created_at: string;
  families: { id: string; name: string; role: string }[];
  contributions: AdminContribution[];
}

export interface AdminFamilyRow {
  id: string;
  name: string;
  member_count: number;
  child_count: number;
  fund_cents: number;
  created_at: string;
}

export interface AdminAuditRow {
  id: string;
  admin_name: string;
  admin_email: string;
  action: string;
  target: string | null;
  detail: Record<string, unknown>;
  created_at: string;
}

export interface AdminFamilyDetail {
  id: string;
  name: string;
  created_at: string;
  fund_cents: number;
  max_upload_mb: number;
  members: {
    user_id: string;
    display_name: string;
    email: string;
    role: string;
    status: string;
    disabled: boolean;
  }[];
  children: {
    id: string;
    first_name: string;
    fund_cents: number;
    fund_account_status: FundAccountStatus;
    stripe_account_id: string | null;
  }[];
  contributions: AdminContribution[];
}

export interface AdminBugRow {
  id: string;
  title: string;
  body: string;
  status: "pending" | "verified" | "rejected";
  reporter: string;
  media_id: string | null;
  created_at: string;
  reviewed_at: string | null;
}

interface Page<T> {
  total: number;
  items: T[];
}

function qs(params: Record<string, string | undefined>): string {
  const p = Object.entries(params).filter(([, v]) => v);
  return p.length ? "?" + p.map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&") : "";
}

export const adminApi = {
  overview: () => request<AdminOverview>("/admin/overview"),
  users: (q?: string) => request<Page<AdminUserRow>>(`/admin/users${qs({ q })}`),
  user: (id: string) => request<AdminUserDetail>(`/admin/users/${id}`),
  families: (q?: string) => request<Page<AdminFamilyRow>>(`/admin/families${qs({ q })}`),
  family: (id: string) => request<AdminFamilyDetail>(`/admin/families/${id}`),
  setFamilySettings: (id: string, maxUploadMb: number) =>
    request<AdminFamilyDetail>(`/admin/families/${id}/settings`, {
      method: "POST",
      body: JSON.stringify({ max_upload_mb: maxUploadMb }),
    }),
  contributions: (q?: string, status?: string) =>
    request<Page<AdminContribution>>(`/admin/contributions${qs({ q, status })}`),
  contributionsCsvUrl: (q?: string, status?: string) =>
    `${API_URL}/admin/contributions.csv${qs({ q, status })}`,
  refund: (contributionId: string, amountCents?: number) =>
    request<AdminContribution>(`/admin/contributions/${contributionId}/refund`, {
      method: "POST",
      body: JSON.stringify({ amount_cents: amountCents ?? null }),
    }),
  reconcile: (contributionId: string) =>
    request<AdminContribution>(`/admin/contributions/${contributionId}/reconcile`, {
      method: "POST",
    }),
  bugs: (status?: string) => request<AdminBugRow[]>(`/admin/bugs${qs({ status })}`),
  auditActions: () => request<string[]>("/admin/audit/actions"),
  auditCsvUrl: (action?: string, since?: string, until?: string) =>
    `${API_URL}/admin/audit.csv${qs({ action, since, until })}`,
  decideBug: (bugId: string, decision: "verify" | "reject") =>
    request<AdminBugRow>(`/admin/bugs/${bugId}/${decision}`, { method: "POST" }),
  setRole: (userId: string, role: "user" | "admin") =>
    request<{ id: string; role: string }>(`/admin/users/${userId}/role`, {
      method: "POST",
      body: JSON.stringify({ role }),
    }),
  setStatus: (userId: string, disabled: boolean) =>
    request<{ id: string; disabled: boolean }>(`/admin/users/${userId}/status`, {
      method: "POST",
      body: JSON.stringify({ disabled }),
    }),
  impersonate: (userId: string) =>
    request<{ access_token: string; expires_in_minutes: number; display_name: string; email: string }>(
      `/admin/users/${userId}/impersonate`,
      { method: "POST" }
    ),
  audit: (action?: string, since?: string, until?: string) =>
    request<Page<AdminAuditRow>>(`/admin/audit${qs({ action, since, until })}`),
  /** Platform-wide announcement. dry_run returns reach counts without sending. */
  broadcast: (payload: {
    title: string;
    body: string;
    url?: string;
    include_email: boolean;
    dry_run: boolean;
  }) => request<AdminBroadcastResult>("/admin/broadcast", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
};

/** Reach/delivery counts from POST /admin/broadcast. Fields are optional
 * defensively — treat missing as 0 when rendering. */
export interface AdminBroadcastResult {
  dry_run?: boolean;
  bell?: number;
  push?: number;
  email?: number;
}

// --- impersonation ("view as") session management ---

const ADMIN_BACKUP_KEY = "futureroots_admin_token";
const IMPERSONATING_KEY = "futureroots_impersonating";

/** Enter view-as: stash the admin token, activate the user token. */
export function beginImpersonation(userToken: string, label: string) {
  const current = getToken();
  if (current) localStorage.setItem(ADMIN_BACKUP_KEY, current);
  localStorage.setItem(IMPERSONATING_KEY, label);
  setToken(userToken);
}

/** Exit view-as: restore the admin token. */
export function endImpersonation() {
  const backup = localStorage.getItem(ADMIN_BACKUP_KEY);
  localStorage.removeItem(IMPERSONATING_KEY);
  localStorage.removeItem(ADMIN_BACKUP_KEY);
  setToken(backup);
}

export function impersonationLabel(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(IMPERSONATING_KEY);
}

/** The CSV download must carry the token; fetch as a blob and save. */
export async function downloadCsv(url: string, filename: string) {
  const res = await fetch(url, { headers: { Authorization: `Bearer ${getToken()}` } });
  if (!res.ok) throw new ApiError(res.status, "Download failed");
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}
