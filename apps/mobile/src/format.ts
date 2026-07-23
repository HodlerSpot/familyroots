// Pure formatting helpers shared by the read screens. These mirror the web
// app's apps/web/src/lib/text.ts + the feed's relative-time helpers verbatim in
// behavior, so copy reads identically on both platforms. No user-facing
// em-dashes here (brand rule); these produce short "3m ago" style strings.

/** "just now" / "5m ago" / "3h ago" / a locale date. Matches web feed.tsx. */
export function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

/** Inbox relative time (docs/brand/notifications-copy.md §4). Matches web
 * notification-bell.tsx: "Just now" / "5m ago" / "Yesterday" / weekday / date. */
export function relativeTime(iso: string): string {
  const then = new Date(iso);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000);
  if (seconds < 60) return "Just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(then)) / 86400000);
  if (dayDiff === 1) return "Yesterday";
  if (dayDiff < 7) return then.toLocaleDateString("en-US", { weekday: "long" });
  if (then.getFullYear() === now.getFullYear())
    return then.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  return then.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
}

/** "January 5, 2027" — the long calendar form used on plan/renewal surfaces.
 * Mirrors the web app's formatLongDate (apps/web/src/lib/text.ts). */
export function formatLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}

/** Split a non-negative second count into whole hours and minutes. */
function hoursAndMinutes(seconds: number): { hours: number; minutes: number } {
  const total = Math.max(0, Math.floor(seconds || 0));
  return { hours: Math.floor(total / 3600), minutes: Math.floor((total % 3600) / 60) };
}

/** Long spoken form: "18 hours and 42 minutes", "less than a minute". */
export function formatDurationLong(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total < 60) return "less than a minute";
  const { hours, minutes } = hoursAndMinutes(total);
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  if (minutes > 0) parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  return parts.join(" and ");
}

/** Compact chip form: "18h 42m", "42m", "2h", "<1m". */
export function formatDurationShort(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total < 60) return "<1m";
  const { hours, minutes } = hoursAndMinutes(total);
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  return parts.join(" ");
}

/** Wrap a family name for mid-sentence use. Matches web text.ts familyPhrase. */
export function familyPhrase(name: string, opts?: { capitalize?: boolean }): string {
  let phrase = name.trim();
  if (!phrase.toLowerCase().endsWith("family")) phrase = `${phrase} family`;
  if (!name.trim().toLowerCase().startsWith("the ")) {
    phrase = `${opts?.capitalize ? "The" : "the"} ${phrase}`;
  } else if (opts?.capitalize) {
    phrase = phrase.charAt(0).toUpperCase() + phrase.slice(1);
  }
  return phrase;
}
