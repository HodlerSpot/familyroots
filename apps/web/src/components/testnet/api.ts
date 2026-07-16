// Testnet harness API client. Only ever imported inside the dynamically
// loaded testnet shell, so none of this ships in family-product builds.

import { ensureMediaToken, getToken, mediaUrl } from "@/lib/api";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface QuestOut {
  action: string;
  label: string;
  hint: string;
  points: number;
  daily_cap: number;
  once: boolean;
  times_completed: number;
  points_earned: number;
  completed_today: number;
}

export interface QuestBoard {
  wallet_address: string;
  display_name: string | null;
  invite_email: string;
  total_points: number;
  quests: QuestOut[];
  x_username: string | null;
  // X profile picture when connected; null means render the wallet identicon.
  avatar_url: string | null;
}

export interface LeaderboardEntry {
  rank: number;
  display_name: string;
  points: number;
  is_me: boolean;
  // Full lowercase wallet address: the identicon seed when avatar_url is null.
  wallet: string;
  avatar_url: string | null;
}

export interface Leaderboard {
  entries: LeaderboardEntry[];
  my_rank: number | null;
  my_points: number | null;
}

export interface BugReport {
  id: string;
  title: string;
  body: string;
  status: "pending" | "verified" | "rejected";
  media_id: string | null;
  // API path for the screenshot; load it via mediaUrl(media_id), which appends
  // the short-lived media-only token (never the session JWT)
  image_url: string | null;
  created_at: string;
  reviewed_at: string | null;
}

async function req<T>(path: string, options: RequestInit = {}): Promise<T> {
  // Testers are backed by real users, so the shared media-token flow applies:
  // keep the short-lived token fresh for bug-screenshot <img> tags.
  await ensureMediaToken();
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
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

export const testnetApi = {
  nonce: (address: string) =>
    req<{ nonce: string; message: string }>("/testnet/auth/nonce", {
      method: "POST",
      body: JSON.stringify({ address }),
    }),
  verify: (address: string, signature: string) =>
    req<{ access_token: string }>("/testnet/auth/verify", {
      method: "POST",
      body: JSON.stringify({ address, signature }),
    }),
  quests: () => req<QuestBoard>("/testnet/quests"),
  leaderboard: () => req<Leaderboard>("/testnet/leaderboard"),
  setProfile: (display_name: string) =>
    req<{ wallet_address: string; display_name: string | null }>("/testnet/profile", {
      method: "POST",
      body: JSON.stringify({ display_name }),
    }),
  submitBug: (bug: { title: string; body: string; media_id?: string }) =>
    req<BugReport>("/testnet/bugs", {
      method: "POST",
      body: JSON.stringify(bug),
    }),
  myBugs: () => req<BugReport[]>("/testnet/bugs"),
  // Upload a screenshot for a bug report via the shared media pipeline:
  // create -> PUT bytes -> complete. Returns the media_id to attach.
  uploadBugImage: async (file: File): Promise<string> => {
    const ticket = await req<{ media_id: string; upload_url: string }>(
      "/testnet/bugs/media",
      { method: "POST", body: JSON.stringify({ content_type: file.type }) }
    );
    const token = getToken();
    const isApiPath = ticket.upload_url.startsWith("/");
    const url = isApiPath ? `${API_URL}${ticket.upload_url}` : ticket.upload_url;
    const headers: Record<string, string> = { "Content-Type": file.type };
    if (isApiPath) headers.Authorization = `Bearer ${token}`;
    const put = await fetch(url, { method: "PUT", headers, body: file });
    if (!put.ok) throw new Error("Upload failed");
    await req<void>(`/media/${ticket.media_id}/complete`, { method: "POST" });
    return ticket.media_id;
  },
  // Shared helper: carries the media-only token, never the session JWT.
  mediaUrl: (mediaId: string) => mediaUrl(mediaId),
  xStart: () =>
    req<{ authorize_url: string }>("/testnet/auth/x/start", { method: "POST" }),
  xCallback: (code: string, state: string) =>
    req<{
      wallet_address: string;
      display_name: string | null;
      x_username: string | null;
      x_avatar_url: string | null;
    }>("/testnet/auth/x/callback", {
      method: "POST",
      body: JSON.stringify({ code, state }),
    }),
  xDisconnect: () =>
    req<{ wallet_address: string; x_username: string | null }>(
      "/testnet/auth/x/disconnect",
      { method: "POST" }
    ),
};
