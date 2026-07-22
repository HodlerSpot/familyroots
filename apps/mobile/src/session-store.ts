// Native session persistence: an Expo SecureStore-backed SessionStore.
//
// The shared api-client requires SessionStore.read() to be SYNCHRONOUS (the
// request path reads the token inline before every call), but SecureStore is
// async. We bridge that by hydrating the persisted record into an in-memory
// cache exactly once at app boot (`hydrateSession`, awaited by the root layout
// behind the splash screen); thereafter read() returns the cache synchronously
// and write()/clear() update the cache immediately while persisting to
// SecureStore in the background (fire-and-forget).
//
// Native sessions are ALWAYS "remembered" (there is no shared-computer /
// per-tab distinction like the web's sessionStorage vs localStorage split), so
// every record we persist carries remembered:true and the durable
// SESSION_REFRESH_WINDOW keeps an active session alive indefinitely.
import * as SecureStore from "expo-secure-store";
import type { SessionRecord, SessionStore } from "@futureroots/api-client";

const KEY = "futureroots.session";

let cache: SessionRecord | null = null;
let hydrated = false;

export const sessionStore: SessionStore = {
  read() {
    return cache;
  },
  write(rec) {
    // Native is always-remembered regardless of what the caller passes.
    cache = { token: rec.token, expEpochMs: rec.expEpochMs, remembered: true };
    const snapshot = cache;
    void SecureStore.setItemAsync(KEY, JSON.stringify(snapshot)).catch(() => {
      // Persistence best-effort; the in-memory cache remains authoritative for
      // this session, and a failed write simply means re-login next cold start.
    });
  },
  clear() {
    cache = null;
    void SecureStore.deleteItemAsync(KEY).catch(() => {});
  },
};

/** Load the persisted session from SecureStore into the in-memory cache. Call
 * once at boot and await it before rendering any authed route, so read() is
 * synchronous and correct from the first request. Idempotent. */
export async function hydrateSession(): Promise<void> {
  if (hydrated) return;
  try {
    const raw = await SecureStore.getItemAsync(KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<SessionRecord>;
      if (parsed && typeof parsed.token === "string") {
        cache = {
          token: parsed.token,
          expEpochMs: typeof parsed.expEpochMs === "number" ? parsed.expEpochMs : null,
          remembered: true,
        };
      }
    }
  } catch {
    cache = null;
  } finally {
    hydrated = true;
  }
}

export function isSessionHydrated(): boolean {
  return hydrated;
}
