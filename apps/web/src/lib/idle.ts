import { getToken, isRememberedSession, setToken } from "@/lib/api";

// A default (non-remembered) session ends after this much inactivity even if
// the tab is left open — the belt-and-braces companion to the token's own
// expiry. Refresh-on-traffic keeps an ACTIVE session alive; this timer bounces
// a truly abandoned tab whose background polling would otherwise keep sliding
// the token. Remembered ("stay logged in") sessions are exempt.
const IDLE_LIMIT_MS = 30 * 60 * 1000;

// Genuine user-presence signals only. We deliberately do NOT reset on API
// traffic: background polling (the bell, a live call) must not defeat an idle
// logout on a walked-away shared computer.
const ACTIVITY_EVENTS = ["mousemove", "mousedown", "keydown", "touchstart", "scroll"] as const;

let timer: ReturnType<typeof setTimeout> | null = null;

function expire() {
  timer = null;
  if (typeof window === "undefined") return;
  if (!getToken() || isRememberedSession()) return;
  setToken(null);
  if (window.location.pathname === "/login") return;
  const next = window.location.pathname + window.location.search;
  window.location.replace(`/login?next=${encodeURIComponent(next)}&reason=timeout`);
}

function schedule() {
  if (timer) clearTimeout(timer);
  timer = setTimeout(expire, IDLE_LIMIT_MS);
}

/** Start the inactivity watch for a default session. No-op on the server and
 * for remembered sessions. Returns a cleanup that removes listeners and the
 * pending timer. */
export function startIdleWatch(): () => void {
  if (typeof window === "undefined" || !getToken() || isRememberedSession()) {
    return () => {};
  }
  // Debounce the reset so a stream of pointer events costs almost nothing.
  let last = 0;
  const reset = () => {
    const now = Date.now();
    if (now - last < 1000) return;
    last = now;
    schedule();
  };
  schedule();
  for (const ev of ACTIVITY_EVENTS) {
    window.addEventListener(ev, reset, { passive: true });
  }
  return () => {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    for (const ev of ACTIVITY_EVENTS) window.removeEventListener(ev, reset);
  };
}
