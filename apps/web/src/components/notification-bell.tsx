"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import { api, InboxItemOut } from "@/lib/api";

const POLL_MS = 60_000;

/** Relative time per docs/brand/notifications-copy.md §4. */
function relativeTime(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;

  // Compare calendar days for "Yesterday" / weekday / date.
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(then)) / 86400000);
  if (dayDiff === 1) return "Yesterday";
  if (dayDiff < 7) return then.toLocaleDateString("en-US", { weekday: "long" });
  if (then.getFullYear() === now.getFullYear())
    return then.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return then.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** Only same-site relative paths are safe to navigate to from a notification.
 * The backend validates this too, but the client shouldn't trust it blindly:
 * reject absolute URLs, protocol-relative ("//host/..."), and anything that
 * isn't a path starting with a single "/". */
function safeInternalUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (!url.startsWith("/") || url.startsWith("//")) return null;
  return url;
}

export function NotificationBell() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);
  const [items, setItems] = useState<InboxItemOut[]>([]);
  const [loading, setLoading] = useState(false);

  const wrapRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const refreshCount = useCallback(async () => {
    try {
      const res = await api.inboxUnreadCount();
      setUnread(typeof res?.count === "number" ? res.count : 0);
    } catch {
      // Leave whatever we had; next poll retries.
    }
  }, []);

  // Poll only while the tab is visible; refetch immediately on route change.
  useEffect(() => {
    let timer: ReturnType<typeof setInterval> | null = null;
    const start = () => {
      if (timer) return;
      void refreshCount();
      timer = setInterval(() => void refreshCount(), POLL_MS);
    };
    const stop = () => {
      if (timer) {
        clearInterval(timer);
        timer = null;
      }
    };
    const onVisibility = () => (document.visibilityState === "visible" ? start() : stop());
    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [refreshCount, pathname]);

  // Close the dropdown and refetch the badge whenever the route changes.
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Outside click / Escape closes.
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function openMenu() {
    setOpen(true);
    setLoading(true);
    try {
      const page = await api.inbox(20);
      setItems(page?.items ?? []);
    } catch {
      setItems([]);
    } finally {
      setLoading(false);
    }
    // Opening the bell clears the unread badge (read-all on open).
    try {
      await api.inboxReadAll();
      setUnread(0);
    } catch {
      // Badge will reconcile on the next poll.
    }
  }

  const badge = unread > 9 ? "9+" : String(unread);

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={
          unread > 0 ? `Notifications, ${unread} unread` : "Notifications"
        }
        onClick={() => (open ? setOpen(false) : void openMenu())}
        className={`relative flex items-center justify-center rounded-full p-2 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 ${
          open ? "bg-emerald-50 text-emerald-700" : "text-stone-500 hover:bg-stone-100"
        }`}
      >
        <BellIcon />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-5 min-w-[1.25rem] items-center justify-center rounded-full bg-red-600 px-1 text-[11px] font-bold leading-none text-white">
            {badge}
          </span>
        )}
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Notifications"
          className="absolute right-0 top-[calc(100%+8px)] z-50 w-[min(22rem,calc(100vw-1.5rem))] overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-lg"
        >
          <div className="border-b border-stone-100 px-4 py-3">
            <h2 className="text-sm font-semibold text-emerald-900">Notifications</h2>
          </div>

          <div className="max-h-[70vh] overflow-y-auto">
            {loading ? (
              <p className="px-4 py-8 text-center text-sm text-stone-500">Loading…</p>
            ) : items.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <p className="font-medium text-stone-700">You&apos;re all caught up.</p>
                <p className="mt-1 text-sm text-stone-500">
                  New family moments will show up here.
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-stone-100">
                {items.map((item) => {
                  const unreadRow = !item.read_at;
                  const href = safeInternalUrl(item.url);
                  const content = (
                    <>
                      <div className="flex items-start justify-between gap-3">
                        <p
                          className={`min-w-0 text-sm ${
                            unreadRow ? "font-semibold text-stone-900" : "font-medium text-stone-700"
                          }`}
                        >
                          {item.title}
                        </p>
                        <span className="shrink-0 text-xs text-stone-400">
                          {relativeTime(item.created_at)}
                        </span>
                      </div>
                      {item.body && (
                        <p className="mt-0.5 text-sm text-stone-600">{item.body}</p>
                      )}
                    </>
                  );
                  const rowClass = `block px-4 py-3 text-left hover:bg-emerald-50 ${
                    unreadRow ? "bg-emerald-50/40" : ""
                  }`;
                  return (
                    <li key={item.id}>
                      {href ? (
                        <a href={href} className={rowClass} onClick={() => setOpen(false)}>
                          {content}
                        </a>
                      ) : (
                        <div className={rowClass}>{content}</div>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function BellIcon() {
  return (
    <svg
      width={22}
      height={22}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden
    >
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}
