// The FutureRoots mobile api-client instance.
//
// Wires the shared, platform-agnostic createApi() to the native adapters:
//   - session:   the SecureStore-backed sync store (session-store.ts)
//   - media:     { mode: "header" } — native sends an Authorization header on
//                GET /media/{id}, so the whole web media-token subsystem is
//                skipped (the API already accepts a bearer there).
//   - upload:    an expo-file-system-based UploadPort (see ./upload) that
//                streams a captured/picked file's bytes straight to the
//                presigned URL the create-media ticket hands back.
//   - onSessionExpired: clears the session and notifies the auth context so the
//                app flips to the unauthenticated stack (no window.location).
import Constants from "expo-constants";
import { createApi } from "@futureroots/api-client";
import { sessionStore } from "./session-store";
import { mobileUpload, type MobileUpload } from "./upload";

const apiUrl =
  (Constants.expoConfig?.extra?.apiUrl as string | undefined) ?? "http://localhost:8000";

export type { MobileUpload };

// The auth context registers here so a 401 on an authenticated call can flip
// the whole app to the login stack. Kept as a module-level hook so the
// (module-scoped) client can reach React state without importing React.
let sessionExpiredHandler: (() => void) | null = null;

/** Register (or clear) the handler invoked when the session lapses. */
export function setSessionExpiredHandler(fn: (() => void) | null): void {
  sessionExpiredHandler = fn;
}

export const client = createApi<MobileUpload>({
  apiUrl,
  fetch: (url, init) => fetch(url, init),
  store: sessionStore,
  media: { mode: "header" },
  upload: mobileUpload,
  isTestnet: false,
  onSessionExpired: () => {
    // The shared client does not clear the store itself; the platform handler
    // owns that (mirrors the web shim).
    client.setToken(null);
    sessionExpiredHandler?.();
  },
});

/** Typed endpoint surface for screens (client.api). */
export const api = client.api;

/** URL for an <Image>/<Video> source. In header mode there is no query
 * credential; callers attach `Authorization: Bearer <token>` themselves. */
export function mediaUrl(mediaId: string): string {
  return client.mediaUrl(mediaId);
}

export function getToken(): string | null {
  return client.getToken();
}
