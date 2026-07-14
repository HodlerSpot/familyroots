"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, getToken, NotificationPrefs } from "@/lib/api";
import { Card, ErrorNote } from "@/components/ui";

type PrefKey = keyof NotificationPrefs;

const TOGGLES: { key: PrefKey; label: string; description: string }[] = [
  {
    key: "email_new_member",
    label: "New family member joins",
    description: "When someone new joins your family circle.",
  },
  {
    key: "email_milestone",
    label: "A milestone is celebrated",
    description: "When a little one reaches a moment worth celebrating.",
  },
  {
    key: "email_memory",
    label: "A new memory is added",
    description: "When someone shares a photo, video, or note.",
  },
  {
    key: "email_legacy",
    label: "Something new in the Legacy Archive",
    description: "When a recipe, story, or piece of wisdom is passed down.",
  },
];

export default function SettingsPage() {
  const router = useRouter();
  const [prefs, setPrefs] = useState<NotificationPrefs | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const savedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=/settings");
      return;
    }
    api
      .notificationPrefs()
      .then(setPrefs)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace("/login?next=/settings");
        else setError(err instanceof ApiError ? err.message : "Couldn't load your settings");
      });
    return () => {
      if (savedTimer.current) clearTimeout(savedTimer.current);
    };
  }, [router]);

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

      <Card>
        <div className="flex items-baseline justify-between gap-4">
          <h2 className="text-lg font-semibold text-emerald-900">Email notifications</h2>
          <span
            className={`text-sm font-medium text-emerald-700 transition-opacity ${
              saved ? "opacity-100" : "opacity-0"
            }`}
            aria-live="polite"
          >
            Saved ✓
          </span>
        </div>
        <p className="mt-1 text-sm text-stone-600">
          Choose which family moments send you an email. You&apos;ll always see everything in
          the app.
        </p>

        {error && (
          <div className="mt-4">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}

        <div className="mt-5 divide-y divide-stone-100">
          {TOGGLES.map((t) => (
            <label
              key={t.key}
              className="flex cursor-pointer items-start justify-between gap-4 py-4"
            >
              <div className="min-w-0">
                <p className="font-medium text-stone-900">{t.label}</p>
                <p className="mt-0.5 text-sm text-stone-600">{t.description}</p>
              </div>
              <input
                type="checkbox"
                className="peer sr-only"
                checked={prefs[t.key]}
                onChange={() => toggle(t.key)}
              />
              <span
                aria-hidden
                className="relative mt-0.5 h-7 w-12 shrink-0 rounded-full bg-stone-300 transition-colors after:absolute after:left-0.5 after:top-0.5 after:h-6 after:w-6 after:rounded-full after:bg-white after:shadow after:transition-transform after:content-[''] peer-checked:bg-emerald-600 peer-checked:after:translate-x-5 peer-focus-visible:ring-2 peer-focus-visible:ring-emerald-400 peer-focus-visible:ring-offset-2"
              />
            </label>
          ))}
        </div>
      </Card>
    </div>
  );
}
