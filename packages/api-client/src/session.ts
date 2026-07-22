// Pure session + media-token policy, lifted verbatim in behavior from the web
// app's api.ts but freed of the browser: every storage/DOM touch is behind an
// injected adapter, so the same policy drives web (two Web Storage stores +
// media-token query param) and native (SecureStore + Authorization header).

/** The session token plus the tracking the refresh policy needs: its expiry
 * (epoch ms, or null when unknown) and whether it is a "stay logged in"
 * (remembered) session. A platform's SessionStore persists exactly this. */
export interface SessionRecord {
  token: string;
  expEpochMs: number | null;
  remembered: boolean;
}

/** Synchronous session persistence. `read()` MUST be sync (the request path
 * reads it inline) — a native store hydrates to memory at boot to honor this.
 * Returns null when there is no session (including on a server render). */
export interface SessionStore {
  read(): SessionRecord | null;
  write(rec: SessionRecord): void;
  clear(): void;
}

/** A cached short-lived media token and its expiry (epoch ms). */
export interface MediaTokenRecord {
  token: string;
  expEpochMs: number;
}

/** Synchronous media-token persistence (web media-token mode only). */
export interface MediaTokenStore {
  read(): MediaTokenRecord | null;
  write(token: string, expEpochMs: number): void;
  clear(): void;
}

/** How the client authorizes media reads. `media-token` mints a short-lived,
 * media-only token carried as `?token=` (browsers can't set headers on
 * <img>/<video>); `header` skips the subsystem entirely and sends an
 * Authorization header (native, where the media endpoint accepts a bearer). */
export type MediaConfig =
  | { mode: "media-token"; store: MediaTokenStore }
  | { mode: "header" };

/** Minimal shape of the endpoints `request()` that the session policy calls
 * (only ever `/auth/refresh` and `/auth/media-token`, always POST). Typed
 * loosely so the real generic RequestFn is assignable without a cycle. */
export type SessionRequest = <T>(path: string, options: { method: string }) => Promise<T>;

export interface SessionDeps {
  apiUrl: string;
  store: SessionStore;
  media: MediaConfig;
  /** Clock injection point (tests). Defaults to Date.now. */
  now?: () => number;
  /** Optional hook fired after a successful silent refresh re-mints the token. */
  onSessionRefreshed?: (rec: SessionRecord) => void;
}

// Refresh a near-expiry token this long before it lapses, so ordinary activity
// keeps a session alive indefinitely: ~10 min for a 30-min default session,
// ~1 day for a 30-day remembered session.
const SESSION_REFRESH_WINDOW_MS = 10 * 60 * 1000;
const REMEMBER_REFRESH_WINDOW_MS = 24 * 60 * 60 * 1000;
// Refresh when an API call finds less than this much life left on the media
// token, so any normal activity keeps it live long before <img> fetches 401.
const MEDIA_TOKEN_REFRESH_WINDOW_MS = 15 * 60 * 1000;

const B64_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/** Dependency-free base64url -> byte-string decoder (replaces the browser's
 * `atob`, which native lacks). Produces a Latin-1 string byte-for-byte
 * identical to `atob`, so `JSON.parse` reads the JWT claims the same way. */
function decodeBase64url(input: string): string {
  const b64 = input.replace(/-/g, "+").replace(/_/g, "/");
  const padded = b64 + "=".repeat((4 - (b64.length % 4)) % 4);
  let output = "";
  for (let i = 0; i < padded.length; i += 4) {
    const e0 = B64_ALPHABET.indexOf(padded[i]);
    const e1 = B64_ALPHABET.indexOf(padded[i + 1]);
    const c2 = padded[i + 2];
    const c3 = padded[i + 3];
    const e2 = c2 === "=" ? -1 : B64_ALPHABET.indexOf(c2);
    const e3 = c3 === "=" ? -1 : B64_ALPHABET.indexOf(c3);
    const n = (e0 << 18) | (e1 << 12) | ((e2 < 0 ? 0 : e2) << 6) | (e3 < 0 ? 0 : e3);
    output += String.fromCharCode((n >> 16) & 0xff);
    if (e2 >= 0) output += String.fromCharCode((n >> 8) & 0xff);
    if (e3 >= 0) output += String.fromCharCode(n & 0xff);
  }
  return output;
}

/** Read the `exp` (seconds since epoch) from a JWT payload, as ms, or null. */
export function decodeJwtExpMs(token: string): number | null {
  try {
    const payload = token.split(".")[1];
    if (!payload) return null;
    const claims = JSON.parse(decodeBase64url(payload));
    return typeof claims.exp === "number" ? claims.exp * 1000 : null;
  } catch {
    return null;
  }
}

/** The stateful session controller: owns the in-flight refresh/media-mint
 * promises (so concurrent traffic dedups to a single call) and exposes the
 * exact getToken/setToken/ensure* surface the web app had, made pure. */
export class SessionController {
  private readonly apiUrl: string;
  private readonly store: SessionStore;
  private readonly media: MediaConfig;
  private readonly now: () => number;
  private readonly onSessionRefreshed?: (rec: SessionRecord) => void;

  private sessionRefreshInflight: Promise<void> | null = null;
  private mediaTokenInflight: Promise<void> | null = null;

  constructor(deps: SessionDeps) {
    this.apiUrl = deps.apiUrl;
    this.store = deps.store;
    this.media = deps.media;
    this.now = deps.now ?? (() => Date.now());
    this.onSessionRefreshed = deps.onSessionRefreshed;
  }

  getToken(): string | null {
    return this.store.read()?.token ?? null;
  }

  /** True when the active session is a "stay logged in" (remembered) token,
   * which is exempt from the idle timeout. */
  isRemembered(): boolean {
    return this.store.read()?.remembered ?? false;
  }

  /** Set (or clear) the session token. `remember` selects the durable store on
   * platforms that have one. Clearing wipes the session; either way the cached
   * media token — which belongs to the previous identity — is cleared. */
  setToken(token: string | null, opts: { remember?: boolean } = {}): void {
    if (token === null) {
      this.store.clear();
    } else {
      this.writeRecord(token, opts.remember ?? false);
    }
    this.clearMediaToken();
  }

  /** Persist a token into the session store, preserving remembered-ness. Does
   * NOT touch the media token (the silent refresh reuses this to slide the same
   * identity's window). */
  private writeRecord(token: string, remembered: boolean): void {
    this.store.write({ token, expEpochMs: decodeJwtExpMs(token), remembered });
  }

  private getMediaToken(): string | null {
    if (this.media.mode !== "media-token") return null;
    return this.media.store.read()?.token ?? null;
  }

  clearMediaToken(): void {
    if (this.media.mode !== "media-token") return;
    this.media.store.clear();
  }

  /** Keep a usable media token cached without a per-image round trip: called on
   * every API request, it is a no-op while fresh, refreshes in the background
   * when nearing expiry, and blocks only when nothing usable is cached
   * (typically once per login/identity switch). No-op in header mode. */
  async ensureMediaToken(request: SessionRequest): Promise<void> {
    if (this.media.mode !== "media-token") return;
    if (!this.getToken()) return;
    const store = this.media.store;
    const rec = store.read();
    const exp = rec?.expEpochMs ?? 0;
    const remaining = exp - this.now();
    const usable = this.getMediaToken() !== null && remaining > 0;
    if (usable && remaining > MEDIA_TOKEN_REFRESH_WINDOW_MS) return;
    this.mediaTokenInflight ??= (async () => {
      try {
        const res = await request<{ media_token: string; expires_in_seconds: number }>(
          "/auth/media-token",
          { method: "POST" }
        );
        store.write(res.media_token, this.now() + res.expires_in_seconds * 1000);
      } catch {
        // Keep whatever we had; the next API call retries the mint.
      } finally {
        this.mediaTokenInflight = null;
      }
    })();
    if (!usable) await this.mediaTokenInflight;
  }

  /** Slide the session window on API traffic: called on every request, it is a
   * no-op while the token has comfortable life left, and background-refreshes
   * via a single in-flight promise once inside the refresh window — so an active
   * user is never logged out mid-task, while an idle session simply ages out.
   * Mirrors ensureMediaToken, but never blocks: the current token is still valid. */
  ensureSessionFresh(request: SessionRequest): void {
    const rec = this.store.read();
    if (!rec) return;
    const remembered = rec.remembered;
    const exp = rec.expEpochMs ?? 0;
    if (!exp) return; // unknown expiry (e.g. a legacy token) — nothing to slide
    const remaining = exp - this.now();
    if (remaining <= 0) return; // already lapsed; the next call's 401 handles it
    const refreshWindow = remembered ? REMEMBER_REFRESH_WINDOW_MS : SESSION_REFRESH_WINDOW_MS;
    if (remaining > refreshWindow) return;
    this.sessionRefreshInflight ??= (async () => {
      try {
        const res = await request<{ access_token: string; expires_in_seconds?: number }>(
          "/auth/refresh",
          { method: "POST" }
        );
        // Re-mint into the SAME store, preserving remembered-ness; keep the
        // media token (same identity) rather than forcing a needless re-mint.
        this.writeRecord(res.access_token, remembered);
        this.onSessionRefreshed?.(this.store.read()!);
      } catch {
        // Keep the current token; a later call refreshes or 401s into re-login.
      } finally {
        this.sessionRefreshInflight = null;
      }
    })();
  }

  /** URL an <img>/<video> tag can load (media-token mode). The `?token=`
   * credential is the short-lived media-ONLY token — never the session JWT —
   * kept fresh by ensureMediaToken() on every API call. In header mode there is
   * no query credential (the caller attaches an Authorization header instead). */
  mediaUrl(mediaId: string): string {
    if (this.media.mode !== "media-token") {
      return `${this.apiUrl}/media/${mediaId}`;
    }
    return `${this.apiUrl}/media/${mediaId}?token=${this.getMediaToken() ?? ""}`;
  }
}
