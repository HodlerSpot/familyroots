import type {
  BadgeOut,
  CallJoin,
  CallState,
  CallToken,
  CapsuleOut,
  CapsuleType,
  ChildOut,
  CommentOut,
  ContributionOut,
  DataExportBundle,
  ErasureReceipt,
  FamilyDetail,
  FamilyRole,
  FamilySummary,
  FeedEventOut,
  FundAccountStatus,
  FundOut,
  GoalOut,
  InboxPage,
  InvitePreview,
  LegacyOut,
  LegacyType,
  MemoryPromptOut,
  MyContribution,
  NotificationPrefs,
  NotificationSettings,
  PlannedCall,
  PredictionBookOut,
  PredictionGameOut,
  PredictionOut,
  PremiumBillingPlan,
  PremiumStatus,
  ReactionSummary,
  ReleaseCondition,
  RewardType,
  SealedRoundOut,
  UserOut,
  VaultItemOut,
  VaultItemType,
} from "@futureroots/types";
import { SessionController } from "./session";
import type { MediaConfig, SessionDeps, SessionRecord, SessionStore } from "./session";

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

// --- injected HTTP shapes (DOM-free; the real fetch/Response are assignable) ---

export interface FetchResponseLike {
  ok: boolean;
  status: number;
  statusText: string;
  json(): Promise<unknown>;
}

export interface RequestInitLike {
  method?: string;
  headers?: Record<string, string>;
  body?: string;
}

export type FetchLike = (url: string, init: RequestInitLike) => Promise<FetchResponseLike>;

/** The generic request wrapper produced by createApi and consumed by callers
 * that live outside the package (e.g. the web-only admin API in the shim). */
export type RequestFn = <T>(path: string, options?: RequestInitLike) => Promise<T>;

/** How the client PUTs a media file's bytes. Kept behind an adapter so the
 * package stays DOM-free: web supplies a `File`-typed port, native an
 * expo-file-system one. */
export interface UploadPort<TFile> {
  /** The file's MIME type (goes on the upload ticket + PUT Content-Type). */
  contentType(file: TFile): string;
  /** PUT the bytes to `url` with the given headers; throw ApiError on failure. */
  put(url: string, file: TFile, headers: Record<string, string>): Promise<void>;
}

export interface ApiConfig<TFile> {
  apiUrl: string;
  fetch: FetchLike;
  store: SessionStore;
  media: MediaConfig;
  upload: UploadPort<TFile>;
  /** Suppress the family-product session redirect (testnet uses wallet auth). */
  isTestnet: boolean;
  /** Invoked on a 401 to an authenticated, non-auth-flow call — the platform's
   * "session lapsed" handler (web: clear + window redirect; native: auth flip). */
  onSessionExpired: () => void;
  onSessionRefreshed?: (rec: SessionRecord) => void;
  now?: () => number;
}

interface TokenResponse {
  access_token: string;
  /** Seconds until the token expires; present on login/signup/refresh. */
  expires_in_seconds?: number;
}

// Background/auth-flow endpoints whose own 401 must NOT trigger the session
// redirect: the login/password calls surface their own errors (and run with no
// token anyway), and the two piggyback calls handle their own failures.
const NO_SESSION_REDIRECT = new Set([
  "/auth/login",
  "/auth/signup",
  "/auth/forgot-password",
  "/auth/reset-password",
  "/auth/refresh",
  "/auth/media-token",
]);

function qs(params: Record<string, string | undefined>): string {
  const p = Object.entries(params).filter(([, v]) => v);
  return p.length ? "?" + p.map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&") : "";
}

/** The public surface createApi returns. */
export interface ApiBundle<TFile> {
  request: RequestFn;
  api: FutureRootsApi<TFile>;
  session: SessionController;
  getToken: () => string | null;
  setToken: (token: string | null, opts?: { remember?: boolean }) => void;
  isRemembered: () => boolean;
  ensureSessionFresh: () => void;
  ensureMediaToken: () => Promise<void>;
  mediaUrl: (mediaId: string) => string;
}

/** Build the api-client bound to one platform's adapters. Generic over the
 * file type so the upload methods keep a precise signature per platform. */
export function createApi<TFile>(config: ApiConfig<TFile>): ApiBundle<TFile> {
  const { apiUrl, fetch: fetchFn, upload, isTestnet, onSessionExpired } = config;

  const session = new SessionController({
    apiUrl,
    store: config.store,
    media: config.media,
    now: config.now,
    onSessionRefreshed: config.onSessionRefreshed,
  } satisfies SessionDeps);

  const request: RequestFn = async <T>(path: string, options: RequestInitLike = {}): Promise<T> => {
    // Piggyback media-token freshness + session sliding on all API traffic, so
    // pages always render live media and an active session never expires.
    if (path !== "/auth/media-token" && path !== "/auth/refresh") {
      await session.ensureMediaToken(request);
      session.ensureSessionFresh(request);
    }
    const token = session.getToken();
    const res = await fetchFn(`${apiUrl}${path}`, {
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
        const body = (await res.json()) as { detail?: unknown };
        const d = body.detail;
        if (typeof d === "string") {
          detail = d;
        } else if (d && typeof d === "object") {
          // Structured error detail, e.g. the 402 premium_required shape:
          // {"code": "premium_required", "capability": "...", "message": "..."}
          const obj = d as { message?: unknown; code?: unknown; capability?: unknown };
          if (typeof obj.message === "string") detail = obj.message;
          if (typeof obj.code === "string") code = obj.code;
          if (typeof obj.capability === "string") capability = obj.capability;
        }
      } catch {
        // non-JSON error body; keep statusText
      }
      // Centralized session-timeout handling replaces the old per-page 401->login
      // checks: any 401 on an authenticated call (session_expired or a rejected
      // token) clears the session and redirects to a warm re-login.
      if (
        res.status === 401 &&
        !isTestnet &&
        !NO_SESSION_REDIRECT.has(path) &&
        session.getToken()
      ) {
        onSessionExpired();
      }
      throw new ApiError(res.status, detail, code, capability);
    }
    if (res.status === 204) return undefined as T;
    return res.json() as Promise<T>;
  };

  /** PUT the file where the ticket points (our API locally, presigned S3 in
   * prod), then confirm so the server marks it usable. */
  async function putAndComplete(
    ticket: { media_id: string; upload_url: string },
    file: TFile
  ): Promise<string> {
    const isApiPath = ticket.upload_url.startsWith("/");
    const url = isApiPath ? `${apiUrl}${ticket.upload_url}` : ticket.upload_url;
    const headers: Record<string, string> = { "Content-Type": upload.contentType(file) };
    if (isApiPath) headers.Authorization = `Bearer ${session.getToken()}`;
    await upload.put(url, file, headers);
    await request<void>(`/media/${ticket.media_id}/complete`, { method: "POST" });
    return ticket.media_id;
  }

  const api = buildApi<TFile>(request, putAndComplete, upload);

  return {
    request,
    api,
    session,
    getToken: () => session.getToken(),
    setToken: (token, opts = {}) => session.setToken(token, opts),
    isRemembered: () => session.isRemembered(),
    ensureSessionFresh: () => session.ensureSessionFresh(request),
    ensureMediaToken: () => session.ensureMediaToken(request),
    mediaUrl: (mediaId) => session.mediaUrl(mediaId),
  };
}

export type FutureRootsApi<TFile> = ReturnType<typeof buildApi<TFile>>;

function buildApi<TFile>(
  request: RequestFn,
  putAndComplete: (
    ticket: { media_id: string; upload_url: string },
    file: TFile
  ) => Promise<string>,
  upload: UploadPort<TFile>
) {
  return {
    signup: (email: string, display_name: string, password: string) =>
      request<{ access_token: string }>("/auth/signup", {
        method: "POST",
        body: JSON.stringify({ email, display_name, password }),
      }),
    login: (email: string, password: string, remember = false) =>
      request<TokenResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password, remember_me: remember }),
      }),
    /** Re-mint the current session, preserving its remember window. Gated
     * server-side by a still-valid token, so an expired session can't refresh. */
    refreshSession: () => request<TokenResponse>("/auth/refresh", { method: "POST" }),
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
    /** This month's gentle memory prompt for a family (the rotating child of the
     * month). Resolves to null for supporters or a family with no children. */
    getMemoryPrompt: (familyId: string) =>
      request<MemoryPromptOut | null>(`/families/${familyId}/memory-prompt`),
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
    notificationPrefs: () => request<NotificationSettings>("/me/notifications"),
    setNotificationPrefs: (prefs: NotificationPrefs) => {
      // The PUT schema is the flat 22-boolean matrix; never echo back the
      // read-only push_public_key that GET piggybacks.
      const { push_public_key: _readOnly, ...body } = prefs as NotificationSettings;
      void _readOnly;
      return request<NotificationSettings>("/me/notifications", {
        method: "PUT",
        body: JSON.stringify(body),
      });
    },

    // Web push enrollment for THIS browser (503 when push isn't configured)
    subscribePush: (sub: { endpoint: string; p256dh: string; auth: string; ua_label: string }) =>
      request<void>("/me/push-subscriptions", {
        method: "POST",
        body: JSON.stringify(sub),
      }),
    unsubscribePush: (endpoint: string) =>
      request<void>("/me/push-subscriptions/unsubscribe", {
        method: "POST",
        body: JSON.stringify({ endpoint }),
      }),

    // In-app notification bell (inbox)
    inbox: (limit = 20, cursor?: string) =>
      request<InboxPage>(`/me/inbox${qs({ limit: String(limit), cursor })}`),
    inboxUnreadCount: () => request<{ count: number }>("/me/inbox/unread-count"),
    inboxReadAll: () => request<void>("/me/inbox/read-all", { method: "POST" }),
    inboxMarkRead: (id: string) => request<void>(`/me/inbox/${id}/read`, { method: "POST" }),

    // A member's own contribution history
    myContributions: () => request<MyContribution[]>("/me/contributions"),

    // --- Your data (GDPR self-serve) ---
    /** Download the caller's own data as a machine-readable JSON bundle
     * (GDPR Art. 15/20). Media is referenced by media_id, not embedded. */
    exportMyData: () => request<DataExportBundle>("/me/data-export", { method: "POST" }),
    /** Permanently erase the caller's own account. Requires a fresh password
     * step-up (sent in the DELETE body); returns the erasure receipt. Financial
     * records are retained by law with the caller's identity severed. */
    deleteMyAccount: (password: string) =>
      request<ErasureReceipt>("/me", {
        method: "DELETE",
        body: JSON.stringify({ password }),
      }),

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

    // --- Future Predictions ---
    /** The game surface for a child: open round + live cloud + attributed list.
     * Supporters may call it too (they get a date-free view). */
    getPredictionGame: (childId: string) =>
      request<PredictionGameOut>(`/children/${childId}/predictions`),
    /** Add one prediction to the open round. Up to three per member per year;
     * the API returns 409 with a warm message on the 4th. */
    addPrediction: (childId: string, body: string) =>
      request<PredictionOut>(`/children/${childId}/predictions`, {
        method: "POST",
        body: JSON.stringify({ body }),
      }),
    /** Edit one of your own predictions while the round is open. */
    editPrediction: (predictionId: string, body: string) =>
      request<PredictionOut>(`/predictions/${predictionId}`, {
        method: "PATCH",
        body: JSON.stringify({ body }),
      }),
    /** Remove a prediction (your own, or any as a parent/guardian). */
    deletePrediction: (predictionId: string) =>
      request<void>(`/predictions/${predictionId}`, { method: "DELETE" }),
    /** Family-only: the strip of sealed years waiting for the 18th birthday. */
    listSealedPredictionRounds: (childId: string) =>
      request<SealedRoundOut[]>(`/children/${childId}/predictions/rounds`),
    /** Family-only: the released Book of Predictions. */
    getPredictionBook: (childId: string) =>
      request<PredictionBookOut>(`/children/${childId}/predictions/book`),

    listLegacy: (familyId: string) => request<LegacyOut[]>(`/families/${familyId}/legacy`),
    addLegacy: (
      familyId: string,
      item: { type: LegacyType; title: string; body?: string; media_id?: string }
    ) =>
      request<LegacyOut>(`/families/${familyId}/legacy`, {
        method: "POST",
        body: JSON.stringify(item),
      }),
    uploadFamilyMedia: async (familyId: string, file: TFile): Promise<string> => {
      const ticket = await request<{ media_id: string; upload_url: string }>(
        `/families/${familyId}/media`,
        { method: "POST", body: JSON.stringify({ content_type: upload.contentType(file) }) }
      );
      return putAndComplete(ticket, file);
    },

    uploadMedia: async (childId: string, file: TFile): Promise<string> => {
      const ticket = await request<{ media_id: string; upload_url: string }>(
        `/children/${childId}/media`,
        { method: "POST", body: JSON.stringify({ content_type: upload.contentType(file) }) }
      );
      return putAndComplete(ticket, file);
    },

    // A member's own profile photo (headshot shown when their camera is off).
    uploadMyAvatar: async (file: TFile): Promise<UserOut> => {
      const ticket = await request<{ media_id: string; upload_url: string }>("/me/media", {
        method: "POST",
        body: JSON.stringify({ content_type: upload.contentType(file) }),
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
}
