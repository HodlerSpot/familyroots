export type FamilyRole =
  | "parent"
  | "grandparent"
  | "relative"
  | "aunt"
  | "uncle"
  | "cousin"
  | "guardian"
  | "supporter";

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
  /** Estimated seconds of meaningful memories preserved for this child.
   *  A non-negative integer for members with full child access; null for
   *  supporters (the total aggregates content they can't see). May be
   *  undefined at runtime on older payloads, so treat defensively. */
  future_gifts_seconds: number | null;
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
  | "fund_activated"
  | "memory_added"
  | "capsule_created"
  | "capsule_released"
  | "member_joined"
  | "member_left"
  | "premium_activated"
  | "premium_gifted"
  | "prediction_added"
  | "predictions_sealed"
  | "predictions_released";

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

/** The monthly memory-prompt state for a family, computed on read.
 * `null` from the API means "no prompt" (a supporter, or a family with no
 * children). `satisfied` is true once the caller has already added a memory
 * this month, so the in-app card can quietly hide itself. */
export interface MemoryPromptOut {
  /** The prompt's calendar month, "YYYY-MM" (UTC) — used to key a per-month
   * client-side dismiss so the card never nags twice in the same month. */
  period: string;
  child: { id: string; first_name: string };
  satisfied: boolean;
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

/** The kinds of family moments FutureRoots can notify about. Each kind has an
 * email and a web-push toggle (22 booleans total). */
export type NotificationKind =
  | "call_live"
  | "contribution"
  | "fund_activated"
  | "capsule_sealed"
  | "capsule_released"
  | "new_member"
  | "milestone"
  | "memory"
  | "legacy"
  | "announcement"
  | "memory_request";

export interface NotificationPrefs {
  email_new_member: boolean;
  email_milestone: boolean;
  email_memory: boolean;
  email_legacy: boolean;
  email_call_live: boolean;
  email_contribution: boolean;
  email_fund_activated: boolean;
  email_capsule_sealed: boolean;
  email_capsule_released: boolean;
  email_announcements: boolean;
  email_memory_request: boolean;
  push_new_member: boolean;
  push_milestone: boolean;
  push_memory: boolean;
  push_legacy: boolean;
  push_call_live: boolean;
  push_contribution: boolean;
  push_fund_activated: boolean;
  push_capsule_sealed: boolean;
  push_capsule_released: boolean;
  push_announcements: boolean;
  push_memory_request: boolean;
}

/** GET /me/notifications also carries the server's web-push public key.
 * Empty/absent means push is not configured (feature dark) — hide the
 * browser-notifications card entirely. */
export interface NotificationSettings extends NotificationPrefs {
  push_public_key?: string | null;
}

/** One row in the in-app notification bell. */
export interface InboxItemOut {
  id: string;
  kind: string;
  title: string;
  body: string | null;
  url: string | null;
  read_at: string | null;
  created_at: string;
}

/** GET /me/inbox returns a page, not a bare array. */
export interface InboxPage {
  items: InboxItemOut[];
  next_cursor: string | null;
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

// --- Future Predictions (the yearly family word-cloud game) ---

/** One word in the live cloud, sized by how many predictions used it. */
export interface CloudWordOut {
  word: string;
  weight: number;
}

/** One prediction in the open round's attributed list. */
export interface PredictionOut {
  id: string;
  body: string;
  author_name: string;
  /** The caller wrote this one (show edit + remove). */
  is_mine: boolean;
  /** The caller may remove it (their own, or they are a parent/guardian). */
  can_delete: boolean;
  created_at: string;
}

/** The open round: the live cloud + the attributed list + the caller's slots.
 * `seals_on` and `year` are BOTH null for supporters (both are birthdate-derived
 * dates they must never see) — rely on them being null rather than reconstructing
 * anything. */
export interface OpenRoundOut {
  id: string;
  year: number | null;
  seals_on: string | null;
  cloud: CloudWordOut[];
  predictions: PredictionOut[];
  /** The caller's own prediction ids in this round (for remaining-slot math). */
  my_prediction_ids: string[];
  /** The per-member cap for the round (3). */
  max_per_member: number;
}

/** The game surface for one child. `round` is null when the game is complete
 * (family, once the book is open) or idle (supporter, nothing to show).
 * `completed` is true only for family once the book has released. */
export interface PredictionGameOut {
  child_first_name: string;
  round: OpenRoundOut | null;
  completed: boolean;
}

/** A family-only locked year (no counts, no content, no peek). */
export interface SealedRoundOut {
  id: string;
  year: number;
  sealed_at: string;
  /** The 18th birthday the sealed years all open on. */
  opens_on: string;
}

/** One prediction inside a released Book chapter. */
export interface BookPredictionOut {
  body: string;
  author_name: string;
  created_at: string;
}

/** One released year of the Book of Predictions: the keepsake image + the full
 * attributed list. */
export interface BookChapterOut {
  round_id: string;
  year: number;
  age: number;
  /** The sealed keepsake image (a PNG), served via mediaUrl(). Null if a year
   * sealed without a rendered image. */
  cloud_media_id: string | null;
  media_content_type: string | null;
  predictions: BookPredictionOut[];
}

/** The released Book of Predictions (family-only). Empty chapters until the
 * 18th birthday; skipped years are silently absent. */
export interface PredictionBookOut {
  child_first_name: string;
  chapters: BookChapterOut[];
}

/** The GDPR data-export bundle (POST /me/data-export). It is a large nested
 * object assembled server-side (see apps/api/app/services/export.py); we type the
 * top level for the download flow and leave each section permissive, since the
 * client only serializes it to a file rather than reading into it. Media is
 * listed by reference (media_id + content_type) under `media`; the bytes are
 * fetched from the media endpoint in the app. */
export interface DataExportBundle {
  generated_at: string | null;
  scope: string;
  subject: Record<string, unknown>;
  profile: Record<string, unknown>;
  /** Every media file, listed by media_id + content_type (not the bytes). */
  media: unknown[];
  media_retrieval: string;
  /** All other sections (families, contributions, authored content, etc.). */
  [section: string]: unknown;
}

/** The erasure receipt (DELETE /me) — a structured log line the server returns
 * after the account is erased. Permissive: the client does not read into it. */
export type ErasureReceipt = Record<string, unknown>;
