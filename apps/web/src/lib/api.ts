const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type FamilyRole = "parent" | "grandparent" | "relative" | "guardian";

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
}

export interface FamilySummary {
  id: string;
  name: string;
  role: FamilyRole;
}

export interface MemberOut {
  id: string;
  user: UserOut;
  role: FamilyRole;
  status: string;
}

export interface ChildOut {
  id: string;
  first_name: string;
  birthdate: string;
}

export interface FamilyDetail {
  id: string;
  name: string;
  members: MemberOut[];
  children: ChildOut[];
}

export interface InvitePreview {
  family_name: string;
  role: FamilyRole;
  invited_by: string;
}

export type VaultItemType = "photo" | "video" | "voice" | "message" | "document" | "achievement";

export interface VaultItemOut {
  id: string;
  type: VaultItemType;
  title: string;
  body: string | null;
  media_id: string | null;
  media_content_type: string | null;
  created_by_name: string;
  created_at: string;
}

export type FeedEventType =
  | "milestone"
  | "achievement"
  | "contribution"
  | "memory_added"
  | "capsule_created"
  | "capsule_released"
  | "member_joined";

export interface FeedEventOut {
  id: string;
  type: FeedEventType;
  child_id: string | null;
  actor_name: string;
  payload: Record<string, string | number | null>;
  created_at: string;
}

export type RewardType = "cash" | "fund_contribution" | "badge" | "privilege";

export interface GoalOut {
  id: string;
  title: string;
  description: string | null;
  reward_type: RewardType;
  reward_amount_cents: number | null;
  currency: string;
  status: "active" | "completed" | "archived";
  due_at: string | null;
  completed_at: string | null;
}

export interface BadgeOut {
  id: string;
  label: string;
  icon: string;
  awarded_at: string;
}

export interface ContributionOut {
  id: string;
  amount_cents: number;
  currency: string;
  fee_cents: number;
  message: string | null;
  status: "pending" | "succeeded" | "failed" | "refunded";
  created_at: string;
  client_secret: string | null;
}

export interface FundOut {
  child_id: string;
  currency: string;
  balance_cents: number;
  entries: {
    id: string;
    amount_cents: number;
    entry_type: string;
    contributor_name: string | null;
    message: string | null;
    created_at: string;
  }[];
}

export function formatMoney(cents: number, currency = "USD"): string {
  return new Intl.NumberFormat("en-US", { style: "currency", currency }).format(cents / 100);
}

export type CapsuleType = "letter" | "audio" | "video";
export type ReleaseCondition = "age" | "date" | "milestone";

export interface CapsuleOut {
  id: string;
  type: CapsuleType;
  status: "sealed" | "released";
  release_condition: ReleaseCondition;
  release_age: number | null;
  release_date: string | null;
  release_milestone: string | null;
  created_by_name: string;
  is_mine: boolean;
  body: string | null;
  media_id: string | null;
  media_content_type: string | null;
  released_at: string | null;
  created_at: string;
}

export type LegacyType = "story" | "recipe" | "document" | "photo" | "wisdom";

export interface LegacyOut {
  id: string;
  type: LegacyType;
  title: string;
  body: string | null;
  media_id: string | null;
  media_content_type: string | null;
  created_by_name: string;
  created_at: string;
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("futureroots_token");
}

export function setToken(token: string | null) {
  if (token === null) localStorage.removeItem("futureroots_token");
  else localStorage.setItem("futureroots_token", token);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options.headers,
    },
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

/** PUT the file where the ticket points (our API locally, presigned S3 in
 * prod), then confirm so the server marks it usable. */
async function putAndComplete(
  ticket: { media_id: string; upload_url: string },
  file: File
): Promise<string> {
  const isApiPath = ticket.upload_url.startsWith("/");
  const url = isApiPath ? `${API_URL}${ticket.upload_url}` : ticket.upload_url;
  const headers: Record<string, string> = { "Content-Type": file.type };
  if (isApiPath) headers.Authorization = `Bearer ${getToken()}`;
  const res = await fetch(url, { method: "PUT", headers, body: file });
  if (!res.ok) throw new ApiError(res.status, "Upload failed");
  await request<void>(`/media/${ticket.media_id}/complete`, { method: "POST" });
  return ticket.media_id;
}

export const api = {
  signup: (email: string, display_name: string, password: string) =>
    request<{ access_token: string }>("/auth/signup", {
      method: "POST",
      body: JSON.stringify({ email, display_name, password }),
    }),
  login: (email: string, password: string) =>
    request<{ access_token: string }>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<UserOut>("/auth/me"),
  forgotPassword: (email: string) =>
    request<void>("/auth/forgot-password", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),
  resetPassword: (token: string, new_password: string) =>
    request<void>("/auth/reset-password", {
      method: "POST",
      body: JSON.stringify({ token, new_password }),
    }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>("/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password, new_password }),
    }),

  myFamilies: () => request<FamilySummary[]>("/families"),
  createFamily: (name: string) =>
    request<FamilySummary>("/families", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  familyDetail: (id: string) => request<FamilyDetail>(`/families/${id}`),

  addChild: (familyId: string, first_name: string, birthdate: string, parental_consent: boolean) =>
    request<ChildOut>(`/families/${familyId}/children`, {
      method: "POST",
      body: JSON.stringify({ first_name, birthdate, parental_consent }),
    }),

  createInvite: (familyId: string, email: string, role: FamilyRole) =>
    request<{ id: string }>(`/families/${familyId}/invites`, {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),
  previewInvite: (token: string) => request<InvitePreview>(`/invites/${token}`),
  acceptInvite: (token: string) =>
    request<FamilySummary>("/invites/accept", {
      method: "POST",
      body: JSON.stringify({ token }),
    }),

  listVault: (childId: string) => request<VaultItemOut[]>(`/children/${childId}/vault`),
  addVaultItem: (
    childId: string,
    item: { type: VaultItemType; title: string; body?: string; media_id?: string }
  ) =>
    request<VaultItemOut>(`/children/${childId}/vault`, {
      method: "POST",
      body: JSON.stringify(item),
    }),
  postMilestone: (
    childId: string,
    milestone: { title: string; description?: string; media_id?: string }
  ) =>
    request<VaultItemOut>(`/children/${childId}/milestones`, {
      method: "POST",
      body: JSON.stringify(milestone),
    }),
  familyFeed: (familyId: string) => request<FeedEventOut[]>(`/families/${familyId}/feed`),

  listGoals: (childId: string) => request<GoalOut[]>(`/children/${childId}/goals`),
  createGoal: (
    childId: string,
    goal: {
      title: string;
      description?: string;
      reward_type: RewardType;
      reward_amount_cents?: number;
    }
  ) =>
    request<GoalOut>(`/children/${childId}/goals`, {
      method: "POST",
      body: JSON.stringify(goal),
    }),
  completeGoal: (goalId: string, notes?: string) =>
    request<GoalOut>(`/goals/${goalId}/complete`, {
      method: "POST",
      body: JSON.stringify({ notes }),
    }),
  listBadges: (childId: string) => request<BadgeOut[]>(`/children/${childId}/badges`),

  createContribution: (
    childId: string,
    c: { amount_cents: number; message?: string; trigger_feed_event_id?: string }
  ) =>
    request<ContributionOut>(`/children/${childId}/contributions`, {
      method: "POST",
      body: JSON.stringify(c),
    }),
  confirmContribution: (contributionId: string) =>
    request<ContributionOut>(`/contributions/${contributionId}/confirm`, { method: "POST" }),
  childFund: (childId: string) => request<FundOut>(`/children/${childId}/fund`),

  listCapsules: (childId: string) => request<CapsuleOut[]>(`/children/${childId}/capsules`),
  createCapsule: (
    childId: string,
    c: {
      type: CapsuleType;
      body?: string;
      media_id?: string;
      release_condition: ReleaseCondition;
      release_age?: number;
      release_date?: string;
      release_milestone?: string;
    }
  ) =>
    request<CapsuleOut>(`/children/${childId}/capsules`, {
      method: "POST",
      body: JSON.stringify(c),
    }),
  releaseCapsule: (capsuleId: string) =>
    request<CapsuleOut>(`/capsules/${capsuleId}/release`, { method: "POST" }),

  listLegacy: (familyId: string) => request<LegacyOut[]>(`/families/${familyId}/legacy`),
  addLegacy: (
    familyId: string,
    item: { type: LegacyType; title: string; body?: string; media_id?: string }
  ) =>
    request<LegacyOut>(`/families/${familyId}/legacy`, {
      method: "POST",
      body: JSON.stringify(item),
    }),
  uploadFamilyMedia: async (familyId: string, file: File): Promise<string> => {
    const ticket = await request<{ media_id: string; upload_url: string }>(
      `/families/${familyId}/media`,
      { method: "POST", body: JSON.stringify({ content_type: file.type }) }
    );
    return putAndComplete(ticket, file);
  },

  uploadMedia: async (childId: string, file: File): Promise<string> => {
    const ticket = await request<{ media_id: string; upload_url: string }>(
      `/children/${childId}/media`,
      { method: "POST", body: JSON.stringify({ content_type: file.type }) }
    );
    return putAndComplete(ticket, file);
  },
};

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
  contributor_name: string;
  child_name: string;
  amount_cents: number;
  refunded_cents: number;
  currency: string;
  status: string;
  created_at: string;
}

export interface AdminUserRow {
  id: string;
  display_name: string;
  email: string;
  role: "user" | "admin";
  family_count: number;
  child_count: number;
  created_at: string;
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
  families: (q?: string) => request<Page<AdminFamilyRow>>(`/admin/families${qs({ q })}`),
  contributions: (q?: string, status?: string) =>
    request<Page<AdminContribution>>(`/admin/contributions${qs({ q, status })}`),
  contributionsCsvUrl: (q?: string, status?: string) =>
    `${API_URL}/admin/contributions.csv${qs({ q, status })}`,
  refund: (contributionId: string, amountCents?: number) =>
    request<AdminContribution>(`/admin/contributions/${contributionId}/refund`, {
      method: "POST",
      body: JSON.stringify({ amount_cents: amountCents ?? null }),
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
  impersonate: (userId: string) =>
    request<{ access_token: string; expires_in_minutes: number; display_name: string; email: string }>(
      `/admin/users/${userId}/impersonate`,
      { method: "POST" }
    ),
  audit: (action?: string, since?: string, until?: string) =>
    request<Page<AdminAuditRow>>(`/admin/audit${qs({ action, since, until })}`),
};

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

/** URL an <img>/<video> tag can load (tags can't send auth headers). */
export function mediaUrl(mediaId: string): string {
  return `${API_URL}/media/${mediaId}?token=${getToken()}`;
}
