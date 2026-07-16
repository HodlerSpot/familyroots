const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type FamilyRole = "parent" | "grandparent" | "relative" | "guardian" | "supporter";

/** Emoji a member can react with on a moment or comment. */
export const REACTION_EMOJI = ["❤️", "👍", "🎉", "😂", "🥰", "😢"] as const;

export interface ReactionSummary {
  emoji: string;
  count: number;
  reacted: boolean;
}

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
  role: "user" | "admin";
  avatar_media_id: string | null;
}

/** Family-level plan, derived server-side. The client uses it for warm
 * affordances only; the API is always the enforcement. */
export type FamilyPlan = "free" | "premium";

/** Recurring billing plan for FutureRoots Premium. */
export type PremiumBillingPlan = "monthly" | "annual";

export interface FamilySummary {
  id: string;
  name: string;
  role: FamilyRole;
  plan: FamilyPlan;
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
  birthdate: string | null;
  avatar_media_id: string | null;
  avatar_content_type: string | null;
}

export interface FamilyDetail {
  id: string;
  name: string;
  members: MemberOut[];
  children: ChildOut[];
  plan: FamilyPlan;
  premium_until: string | null;
  capabilities: string[];
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
  visible_to_supporters: boolean;
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
  | "member_joined"
  | "member_left"
  | "premium_activated"
  | "premium_gifted";

export interface FeedEventOut {
  id: string;
  type: FeedEventType;
  child_id: string | null;
  actor_name: string;
  payload: Record<string, string | number | null>;
  created_at: string;
  reactions: ReactionSummary[];
  comment_count: number;
}

export interface CommentOut {
  id: string;
  author_name: string;
  author_user_id: string;
  body: string;
  created_at: string;
  reactions: ReactionSummary[];
  can_delete: boolean;
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

/** Lifecycle of a child's real Future Fund account. Contributions require active. */
export type FundAccountStatus = "none" | "onboarding" | "active" | "restricted";

export interface FundOut {
  child_id: string;
  currency: string;
  balance_cents: number;
  account_status: FundAccountStatus;
  setup_by_name: string | null;
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
export type ReleaseCondition = "age" | "date" | "milestone" | "goal";

export interface CapsuleOut {
  id: string;
  type: CapsuleType;
  status: "sealed" | "released";
  release_condition: ReleaseCondition;
  release_age: number | null;
  release_date: string | null;
  release_milestone: string | null;
  release_goal_id: string | null;
  release_goal_title: string | null;
  created_by_name: string;
  is_mine: boolean;
  body: string | null;
  media_id: string | null;
  media_content_type: string | null;
  released_at: string | null;
  created_at: string;
  release_votes: number;
  i_voted: boolean;
  can_vote: boolean;
}

export interface NotificationPrefs {
  email_new_member: boolean;
  email_milestone: boolean;
  email_memory: boolean;
  email_legacy: boolean;
}

export interface MyContribution {
  id: string;
  child_name: string;
  family_name: string;
  amount_cents: number;
  currency: string;
  fee_cents: number;
  status: "pending" | "succeeded" | "failed" | "refunded";
  refunded_cents: number;
  message: string | null;
  created_at: string;
}

// --- Family video call ---

export interface CallParticipant {
  user_id: string;
  display_name: string;
  agora_uid: number;
  avatar_media_id: string | null;
  is_you: boolean;
}

export interface CallChildPresent {
  child_id: string;
  first_name: string;
  avatar_media_id: string | null;
  marked_by: string;
}

export interface PlannedCall {
  scheduled_for: string;
  note: string | null;
  set_by: string;
  set_by_name: string;
  updated_at: string;
}

export interface CallState {
  active: boolean;
  call_id: string | null;
  channel_name: string | null;
  started_at: string | null;
  participants: CallParticipant[];
  children_present: CallChildPresent[];
  planned_call: PlannedCall | null;
}

export interface CallJoin {
  app_id: string;
  channel_name: string;
  token: string;
  agora_uid: number;
  expires_at: number;
  call: CallState;
}

export interface CallToken {
  token: string;
  agora_uid: number;
  expires_at: number;
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

// --- FutureRoots Premium (family membership) ---

export interface PremiumSubscription {
  plan: PremiumBillingPlan;
  status: "active" | "past_due" | "canceled";
  current_period_end: string;
  cancel_at_period_end: boolean;
  owner_name: string;
  /** Viewer started this subscription (enables the billing portal button). */
  is_owner: boolean;
}

export interface PremiumGrant {
  gifter_name: string;
  starts_at: string;
  ends_at: string;
  message: string | null;
}

export interface PremiumStatus {
  plan: FamilyPlan;
  premium_until: string | null;
  capabilities: string[];
  /** Viewer is an active parent (may upgrade/cancel/resume). */
  can_manage: boolean;
  /** Viewer is an active non-parent (may gift Premium). */
  can_gift: boolean;
  /** Billing detail; present for parents only (billing trouble is private). */
  subscription: PremiumSubscription | null;
  grants: PremiumGrant[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    /** Machine-readable error code from a structured API error detail,
     * e.g. "premium_required", "already_premium", "use_subscribe". */
    public code: string | null = null,
    /** The gated capability when code === "premium_required". */
    public capability: string | null = null
  ) {
    super(message);
  }
}

/** True when a call failed because the family needs FutureRoots Premium.
 * Callers of gated actions catch this and show the warm upsell, not a toast. */
export function isPremiumRequired(err: unknown): err is ApiError & { capability: string } {
  return err instanceof ApiError && err.status === 402 && err.code === "premium_required";
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("futureroots_token");
}

export function setToken(token: string | null) {
  if (token === null) localStorage.removeItem("futureroots_token");
  else localStorage.setItem("futureroots_token", token);
  // The cached media token belongs to the previous identity (logout, login,
  // impersonation switch) — never carry it across; it re-mints lazily.
  clearMediaToken();
}

// --- media tokens ---
// <img>/<video>/<audio> tags can't send an Authorization header, so media URLs
// must carry a credential in the query string — a leak surface (proxy logs,
// browser history, Referer headers). Trade-off: we keep ?token=, but instead of
// the account's session JWT it is a short-lived token the API honors ONLY on
// GET /media/{id} (it is rejected as a session everywhere else, and session
// JWTs are rejected there), so a leaked media URL exposes at most an hour of
// read-only media access — never the account.

const MEDIA_TOKEN_KEY = "futureroots_media_token";
const MEDIA_TOKEN_EXP_KEY = "futureroots_media_token_exp";
// Refresh when an API call finds less than this much life left, so any normal
// activity keeps the token live long before <img> fetches would start to 401.
const MEDIA_TOKEN_REFRESH_WINDOW_MS = 15 * 60 * 1000;

function getMediaToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(MEDIA_TOKEN_KEY);
}

function clearMediaToken() {
  localStorage.removeItem(MEDIA_TOKEN_KEY);
  localStorage.removeItem(MEDIA_TOKEN_EXP_KEY);
}

let mediaTokenInflight: Promise<void> | null = null;

/** Keep a usable media token cached without a per-image round trip: called on
 * every API request, it is a no-op while fresh, refreshes in the background
 * when nearing expiry, and blocks only when nothing usable is cached
 * (typically once per login/identity switch). */
export async function ensureMediaToken(): Promise<void> {
  if (typeof window === "undefined" || !getToken()) return;
  const exp = Number(localStorage.getItem(MEDIA_TOKEN_EXP_KEY) ?? 0);
  const remaining = exp - Date.now();
  const usable = getMediaToken() !== null && remaining > 0;
  if (usable && remaining > MEDIA_TOKEN_REFRESH_WINDOW_MS) return;
  mediaTokenInflight ??= (async () => {
    try {
      const res = await request<{ media_token: string; expires_in_seconds: number }>(
        "/auth/media-token",
        { method: "POST" }
      );
      localStorage.setItem(MEDIA_TOKEN_KEY, res.media_token);
      localStorage.setItem(
        MEDIA_TOKEN_EXP_KEY,
        String(Date.now() + res.expires_in_seconds * 1000)
      );
    } catch {
      // Keep whatever we had; the next API call retries the mint.
    } finally {
      mediaTokenInflight = null;
    }
  })();
  if (!usable) await mediaTokenInflight;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Piggyback media-token freshness on all API traffic (see ensureMediaToken),
  // so pages always render <img>/<video> URLs with a live token.
  if (path !== "/auth/media-token") await ensureMediaToken();
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
    let code: string | null = null;
    let capability: string | null = null;
    try {
      const body = await res.json();
      const d = body.detail;
      if (typeof d === "string") {
        detail = d;
      } else if (d && typeof d === "object") {
        // Structured error detail, e.g. the 402 premium_required shape:
        // {"code": "premium_required", "capability": "...", "message": "..."}
        if (typeof d.message === "string") detail = d.message;
        if (typeof d.code === "string") code = d.code;
        if (typeof d.capability === "string") capability = d.capability;
      }
    } catch {
      // non-JSON error body; keep statusText
    }
    throw new ApiError(res.status, detail, code, capability);
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
  reportIssue: (title: string, body: string) =>
    request<{ id: string; title: string; status: string }>("/issues", {
      method: "POST",
      body: JSON.stringify({ title, body }),
    }),
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
  /** Step away from a family. The server refuses (409) when the caller is
   * the last active parent; if the caller owns the family's Premium
   * subscription, it stops auto-renewal at the period end. */
  leaveFamily: (familyId: string) =>
    request<void>(`/families/${familyId}/members/me/leave`, { method: "POST" }),
  /** Parent-only: remove another member. Nothing they shared is deleted,
   * and they can be re-invited later. */
  removeFamilyMember: (familyId: string, userId: string) =>
    request<void>(`/families/${familyId}/members/${userId}`, { method: "DELETE" }),

  addChild: (familyId: string, first_name: string, birthdate: string, parental_consent: boolean) =>
    request<ChildOut>(`/families/${familyId}/children`, {
      method: "POST",
      body: JSON.stringify({ first_name, birthdate, parental_consent }),
    }),
  setChildAvatar: (childId: string, media_id: string) =>
    request<ChildOut>(`/children/${childId}/avatar`, {
      method: "POST",
      body: JSON.stringify({ media_id }),
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
  setVaultVisibility: (itemId: string, visible: boolean) =>
    request<VaultItemOut>(`/vault-items/${itemId}/visibility`, {
      method: "PATCH",
      body: JSON.stringify({ visible }),
    }),

  // Family Moments — reactions & comments
  toggleReaction: (target_type: "feed_event" | "comment", target_id: string, emoji: string) =>
    request<{ reactions: ReactionSummary[] }>(`/reactions`, {
      method: "POST",
      body: JSON.stringify({ target_type, target_id, emoji }),
    }),
  listComments: (eventId: string) => request<CommentOut[]>(`/feed-events/${eventId}/comments`),
  addComment: (eventId: string, body: string) =>
    request<CommentOut>(`/feed-events/${eventId}/comments`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),
  deleteComment: (commentId: string) =>
    request<void>(`/comments/${commentId}`, { method: "DELETE" }),

  // Notification preferences (profile)
  notificationPrefs: () => request<NotificationPrefs>("/me/notifications"),
  setNotificationPrefs: (prefs: NotificationPrefs) =>
    request<NotificationPrefs>("/me/notifications", {
      method: "PUT",
      body: JSON.stringify(prefs),
    }),

  // A member's own contribution history
  myContributions: () => request<MyContribution[]>("/me/contributions"),

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

  // Future Fund account (Stripe Connect behind the scenes; server-only ids)
  fundStatus: (childId: string) =>
    request<{ account_status: FundAccountStatus }>(`/children/${childId}/fund/status`),
  startFundSetup: (childId: string) =>
    request<{ url: string }>(`/children/${childId}/fund/setup`, { method: "POST" }),
  fundSetupStatus: (childId: string) =>
    request<{
      account_status: FundAccountStatus;
      payouts_enabled: boolean;
      requirements_due: boolean;
    }>(`/children/${childId}/fund/setup/status`),
  nudgeFundSetup: (childId: string) =>
    request<{ sent: boolean }>(`/children/${childId}/fund/nudge`, { method: "POST" }),

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
      release_goal_id?: string;
    }
  ) =>
    request<CapsuleOut>(`/children/${childId}/capsules`, {
      method: "POST",
      body: JSON.stringify(c),
    }),
  releaseCapsule: (capsuleId: string) =>
    request<CapsuleOut>(`/capsules/${capsuleId}/release`, { method: "POST" }),
  voteReleaseCapsule: (capsuleId: string) =>
    request<CapsuleOut>(`/capsules/${capsuleId}/vote-release`, { method: "POST" }),

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

  // A member's own profile photo (headshot shown when their camera is off).
  uploadMyAvatar: async (file: File): Promise<UserOut> => {
    const ticket = await request<{ media_id: string; upload_url: string }>("/me/media", {
      method: "POST",
      body: JSON.stringify({ content_type: file.type }),
    });
    const media_id = await putAndComplete(ticket, file);
    return request<UserOut>("/me/avatar", {
      method: "POST",
      body: JSON.stringify({ media_id }),
    });
  },

  // --- Family video call ---
  callState: (familyId: string) => request<CallState>(`/families/${familyId}/call`),
  joinCall: (familyId: string) =>
    request<CallJoin>(`/families/${familyId}/call/join`, { method: "POST" }),
  callHeartbeat: (familyId: string) =>
    request<void>(`/families/${familyId}/call/heartbeat`, { method: "POST" }),
  leaveCall: (familyId: string) =>
    request<void>(`/families/${familyId}/call/leave`, { method: "POST" }),
  refreshCallToken: (familyId: string) =>
    request<CallToken>(`/families/${familyId}/call/token`, { method: "POST" }),
  setChildrenPresent: (familyId: string, childIds: string[]) =>
    request<CallState>(`/families/${familyId}/call/children`, {
      method: "PUT",
      body: JSON.stringify({ child_ids: childIds }),
    }),
  setPlannedCall: (familyId: string, scheduledFor: string, note?: string) =>
    request<PlannedCall>(`/families/${familyId}/call/planned`, {
      method: "PUT",
      body: JSON.stringify({ scheduled_for: scheduledFor, note: note ?? null }),
    }),
  clearPlannedCall: (familyId: string) =>
    request<void>(`/families/${familyId}/call/planned`, { method: "DELETE" }),

  // --- FutureRoots Premium (family membership) ---
  getPremiumStatus: (familyId: string) =>
    request<PremiumStatus>(`/families/${familyId}/premium`),
  /** Parent-only: start a Stripe-hosted checkout for the recurring plan.
   * Navigate the browser to the returned checkout_url. */
  createPremiumCheckout: (familyId: string, plan: PremiumBillingPlan) =>
    request<{ checkout_url: string }>(`/families/${familyId}/premium/checkout`, {
      method: "POST",
      body: JSON.stringify({ plan }),
    }),
  /** Non-parent: one-time 12-month gift checkout. The message stays with
   * FutureRoots only; it is never sent to the payment processor. */
  createGiftCheckout: (familyId: string, message?: string) =>
    request<{ checkout_url: string }>(`/families/${familyId}/premium/gift-checkout`, {
      method: "POST",
      body: JSON.stringify({ message: message ?? null }),
    }),
  cancelPremium: (familyId: string) =>
    request<PremiumStatus>(`/families/${familyId}/premium/cancel`, { method: "POST" }),
  resumePremium: (familyId: string) =>
    request<PremiumStatus>(`/families/${familyId}/premium/resume`, { method: "POST" }),
  /** Subscription owner only: hosted billing portal (payment method, receipts). */
  createBillingPortal: (familyId: string) =>
    request<{ portal_url: string }>(`/families/${familyId}/premium/portal`, { method: "POST" }),
  /** Reconcile-on-read; used by the success pages when the webhook is slow. */
  syncPremium: (familyId: string, sessionId?: string) =>
    request<PremiumStatus>(`/families/${familyId}/premium/sync`, {
      method: "POST",
      body: JSON.stringify({ session_id: sessionId ?? null }),
    }),
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

/** URL an <img>/<video> tag can load (tags can't send auth headers). The
 * ?token= credential is the short-lived media-ONLY token — never the session
 * JWT — kept fresh by ensureMediaToken() on every API call. */
export function mediaUrl(mediaId: string): string {
  return `${API_URL}/media/${mediaId}?token=${getMediaToken() ?? ""}`;
}
