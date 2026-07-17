"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, getToken, NotificationPrefs, NotificationSettings } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";

type PrefKey = keyof NotificationPrefs;

// Copy from docs/brand/notifications-copy.md §3 (grouping, descriptions,
// column labels) — used verbatim.
const GROUPS: {
  heading: string;
  rows: { emailKey: PrefKey; pushKey: PrefKey; description: string }[];
}[] = [
  {
    heading: "Family moments",
    rows: [
      {
        emailKey: "email_new_member",
        pushKey: "push_new_member",
        description: "When someone joins your family on FutureRoots.",
      },
      {
        emailKey: "email_milestone",
        pushKey: "push_milestone",
        description: "When a child reaches a milestone worth celebrating.",
      },
      {
        emailKey: "email_memory",
        pushKey: "push_memory",
        description: "When a new photo, video, or memory is added to the vault.",
      },
      {
        emailKey: "email_legacy",
        pushKey: "push_legacy",
        description: "When a new story or piece of wisdom joins your family's archive.",
      },
    ],
  },
  {
    heading: "Money & funds",
    rows: [
      {
        emailKey: "email_contribution",
        pushKey: "push_contribution",
        description: "When someone gives to a child's Future Fund.",
      },
      {
        emailKey: "email_fund_activated",
        pushKey: "push_fund_activated",
        description: "When a child's Future Fund is ready to receive gifts.",
      },
    ],
  },
  {
    heading: "Time capsules",
    rows: [
      {
        emailKey: "email_capsule_sealed",
        pushKey: "push_capsule_sealed",
        description: "When someone seals a time capsule for a child.",
      },
      {
        emailKey: "email_capsule_released",
        pushKey: "push_capsule_released",
        description: "When a time capsule opens.",
      },
    ],
  },
  {
    heading: "Calls",
    rows: [
      {
        emailKey: "email_call_live",
        pushKey: "push_call_live",
        description: "When a family video call starts.",
      },
    ],
  },
  {
    heading: "From FutureRoots",
    rows: [
      {
        emailKey: "email_announcements",
        pushKey: "push_announcements",
        description: "Occasional news and updates from the FutureRoots team.",
      },
    ],
  },
];

/** Convert a URL-safe base64 VAPID public key into the byte array
 * pushManager.subscribe expects as applicationServerKey. */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

/** A warm, human name for this browser (shown to the user later if we ever
 * list enrolled browsers), e.g. "Chrome on Windows". */
function friendlyUaLabel(): string {
  const ua = navigator.userAgent;
  const browser = /Edg\//.test(ua)
    ? "Edge"
    : /Firefox\//.test(ua)
      ? "Firefox"
      : /Chrome\//.test(ua)
        ? "Chrome"
        : /Safari\//.test(ua)
          ? "Safari"
          : "Browser";
  const os = /Windows/.test(ua)
    ? "Windows"
    : /iPhone|iPad|iPod/.test(ua)
      ? "iOS"
      : /Android/.test(ua)
        ? "Android"
        : /Mac/.test(ua)
          ? "Mac"
          : /Linux/.test(ua)
            ? "Linux"
            : "device";
  return `${browser} on ${os}`;
}

function isIOS(): boolean {
  return (
    /iPad|iPhone|iPod/.test(navigator.userAgent) ||
    // iPadOS reports as Mac but has touch points
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1)
  );
}

function isInstalledPwa(): boolean {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

/** The push-enrollment card's state machine (plan §5):
 * - hidden: feature dark (no public key) or unsupported browser
 * - ios-install: iOS Safari outside an installed PWA (no push API there)
 * - blocked: user denied the browser permission
 * - ready: supported, not yet enrolled — show the enable CTA
 * - enabled: this browser is enrolled
 * - working: an enable/disable action is in flight
 */
type PushCardState = "unknown" | "hidden" | "ios-install" | "blocked" | "ready" | "enabled" | "working";

export default function SettingsPage() {
  const router = useRouter();
  const [prefs, setPrefs] = useState<NotificationSettings | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const [pushState, setPushState] = useState<PushCardState>("unknown");
  const [pushError, setPushError] = useState("");

  const resolvePushState = useCallback(async (settings: NotificationSettings) => {
    // Feature dark: the server has no push keys — hide the card entirely.
    if (!settings.push_public_key) {
      setPushState("hidden");
      return;
    }
    if (isIOS() && !isInstalledPwa()) {
      setPushState("ios-install");
      return;
    }
    if (!pushSupported()) {
      setPushState("hidden");
      return;
    }
    if (Notification.permission === "denied") {
      setPushState("blocked");
      return;
    }
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      setPushState(sub ? "enabled" : "ready");
    } catch {
      setPushState("ready");
    }
  }, []);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=/settings");
      return;
    }
    api
      .notificationPrefs()
      .then((p) => {
        setPrefs(p);
        void resolvePushState(p);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login?next=/settings");
        else setError(err instanceof ApiError ? err.message : "Couldn't load your settings");
      });
    return () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, [router, resolvePushState]);

  async function toggle(key: PrefKey) {
    if (!prefs) return;
    const next = { ...prefs, [key]: !prefs[key] };
    const previous = prefs;
    setPrefs(next);
    setError("");
    try {
      await api.setNotificationPrefs(next);
      setSaved(true);
      if (savedTimer.current) clearTimeout(savedTimer.current);
      savedTimer.current = setTimeout(() => setSaved(false), 2000);
    } catch (err) {
      setPrefs(previous); // roll back if it didn't stick
      setError(err instanceof ApiError ? err.message : "We couldn't save that just now. Please try again");
    }
  }

  async function enablePush() {
    if (!prefs?.push_public_key) return;
    setPushError("");
    setPushState("working");
    try {
      const reg = await navigator.serviceWorker.register("/sw.js");
      // The permission prompt fires ONLY here, from this explicit action.
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        setPushState(permission === "denied" ? "blocked" : "ready");
        return;
      }
      const applicationServerKey = urlBase64ToUint8Array(prefs.push_public_key);
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: applicationServerKey.buffer as ArrayBuffer,
      });
      const json = sub.toJSON();
      if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
        throw new Error("incomplete subscription");
      }
      await api.subscribePush({
        endpoint: json.endpoint,
        p256dh: json.keys.p256dh,
        auth: json.keys.auth,
        ua_label: friendlyUaLabel(),
      });
      setPushState("enabled");
    } catch (err) {
      // 503 = the server's push feature went dark between load and click.
      if (err instanceof ApiError && err.status === 503) {
        setPushState("hidden");
        return;
      }
      setPushState("ready");
      setPushError(
        err instanceof ApiError
          ? err.message
          : "We couldn't turn on notifications just now. Please try again"
      );
    }
  }

  async function disablePush() {
    setPushError("");
    setPushState("working");
    let endpoint: string | null = null;
    try {
      const reg = await navigator.serviceWorker.getRegistration("/sw.js");
      const sub = await reg?.pushManager.getSubscription();
      if (sub) {
        endpoint = sub.endpoint;
        await sub.unsubscribe();
      }
    } catch {
      // Browser-side unsubscribe failed; still tell the server below.
    }
    try {
      if (endpoint) await api.unsubscribePush(endpoint);
    } catch {
      // Server will prune the dead subscription on its next send anyway.
    }
    setPushState("ready");
  }

  if (error && !prefs) return <ErrorNote>{error}</ErrorNote>;
  if (prefs === null) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          Back to your families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">Notification settings</h1>
      </div>

      {/* --- "This browser" push enrollment (always first; hidden when dark/unsupported) --- */}
      {pushState !== "hidden" && pushState !== "unknown" && (
        <Card>
          <h2 className="text-lg font-semibold text-emerald-900">This browser</h2>

          {pushState === "ios-install" && (
            <p className="mt-2 text-stone-700">
              On iPhone and iPad, add FutureRoots to your Home Screen first: tap Share, then Add
              to Home Screen. Open FutureRoots from there to turn on push notifications.
            </p>
          )}

          {pushState === "blocked" && (
            <p className="mt-2 text-stone-700">
              Notifications are blocked for FutureRoots in this browser. Look for a lock or bell
              icon next to the address bar to turn them back on.
            </p>
          )}

          {(pushState === "ready" || pushState === "working") && (
            <div className="mt-3">
              <p className="mb-3 text-sm text-stone-600">
                Get a gentle heads-up on this device the moment something happens in your family.
              </p>
              <Button onClick={enablePush} disabled={pushState === "working"}>
                Turn on push notifications on this browser
              </Button>
            </div>
          )}

          {pushState === "enabled" && (
            <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
              <p className="flex items-center gap-2 font-medium text-emerald-800">
                <CheckIcon />
                Push notifications are on for this browser.
              </p>
              <button
                type="button"
                onClick={disablePush}
                className="text-sm font-medium text-stone-500 underline hover:text-stone-700"
              >
                Turn off on this browser
              </button>
            </div>
          )}

          {pushError && (
            <div className="mt-3">
              <ErrorNote>{pushError}</ErrorNote>
            </div>
          )}
        </Card>
      )}

      {/* --- Per-kind preference matrix --- */}
      <Card>
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-lg font-semibold text-emerald-900">What we let you know about</h2>
          <span
            className={`text-sm font-medium text-emerald-700 transition-opacity ${
              saved ? "opacity-100" : "opacity-0"
            }`}
            aria-live="polite"
          >
            Saved ✓
          </span>
        </div>

        {error && (
          <div className="mt-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        <div className="mt-4 space-y-6">
          {GROUPS.map((group) => (
            <section key={group.heading}>
              <div className="flex items-end justify-between gap-4 border-b border-stone-200 pb-2">
                <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
                  {group.heading}
                </h3>
                <div className="flex shrink-0 gap-4">
                  <span className="w-12 text-center text-xs font-medium text-stone-500">Email</span>
                  <span className="w-12 text-center text-xs font-medium text-stone-500">Push</span>
                </div>
              </div>
              <div className="divide-y divide-stone-100">
                {group.rows.map((row) => (
                  <div key={row.emailKey} className="flex items-center justify-between gap-4 py-3.5">
                    <p className="min-w-0 text-stone-800">{row.description}</p>
                    <div className="flex shrink-0 gap-4">
                      <span className="flex w-12 justify-center">
                        <Toggle
                          checked={!!prefs[row.emailKey]}
                          onChange={() => toggle(row.emailKey)}
                          label={`Email: ${row.description}`}
                        />
                      </span>
                      <span className="flex w-12 justify-center">
                        <Toggle
                          checked={!!prefs[row.pushKey]}
                          onChange={() => toggle(row.pushKey)}
                          label={`Push: ${row.description}`}
                        />
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </section>
          ))}
        </div>
      </Card>

      <p className="text-center text-sm text-stone-500">
        No matter what&apos;s on or off above, you&apos;ll always find everything waiting for you
        in the app.
      </p>
    </div>
  );
}

function Toggle({
  checked,
  onChange,
  label,
}: {
  checked: boolean;
  onChange: () => void;
  label: string;
}) {
  return (
    <label className="cursor-pointer">
      <input
        type="checkbox"
        className="peer sr-only"
        checked={checked}
        onChange={onChange}
        aria-label={label}
      />
      <span
        aria-hidden
        className="relative block h-7 w-12 rounded-full bg-stone-300 transition-colors after:absolute after:left-0.5 after:top-0.5 after:h-6 after:w-6 after:rounded-full after:bg-white after:shadow after:transition-transform after:content-[''] peer-checked:bg-emerald-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-400 peer-focus-visible:ring-offset-2"
      />
    </label>
  );
}

function CheckIcon() {
  return (
    <svg
      width={18}
      height={18}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}
