const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type FamilyRole = "parent" | "grandparent" | "relative" | "guardian";

export interface UserOut {
  id: string;
  email: string;
  display_name: string;
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
  | "member_joined";

export interface FeedEventOut {
  id: string;
  type: FeedEventType;
  child_id: string | null;
  actor_name: string;
  payload: Record<string, string | null>;
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
  return res.json();
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

  uploadMedia: async (childId: string, file: File): Promise<string> => {
    const ticket = await request<{ media_id: string; upload_url: string }>(
      `/children/${childId}/media`,
      { method: "POST", body: JSON.stringify({ content_type: file.type }) }
    );
    const token = getToken();
    const res = await fetch(`${API_URL}${ticket.upload_url}`, {
      method: "PUT",
      headers: { Authorization: `Bearer ${token}` },
      body: file,
    });
    if (!res.ok) throw new ApiError(res.status, "Upload failed");
    return ticket.media_id;
  },
};

/** URL an <img>/<video> tag can load (tags can't send auth headers). */
export function mediaUrl(mediaId: string): string {
  return `${API_URL}/media/${mediaId}?token=${getToken()}`;
}
