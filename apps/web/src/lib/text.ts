/** Wrap a family name for mid-sentence use without doubling "the" or "family":
 *  "Smith" -> "the Smith family" · "The Saliga Family" -> "The Saliga Family" */
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

/** "March 12, 2027" style date for user-facing copy (renewals, gift coverage). */
export function formatLongDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
  });
}

/** Split a non-negative second count into whole hours and minutes, dropping any
 *  leftover seconds. Shared by both duration formatters below. */
function hoursAndMinutes(seconds: number): { hours: number; minutes: number } {
  const total = Math.max(0, Math.floor(seconds || 0));
  return { hours: Math.floor(total / 3600), minutes: Math.floor((total % 3600) / 60) };
}

/** Long, spoken form for tooltips: "18 hours and 42 minutes", "3 minutes",
 *  "2 hours". Correct singular/plural, zero components omitted, and anything
 *  under a minute reads as "less than a minute". */
export function formatDurationLong(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total < 60) return "less than a minute";
  const { hours, minutes } = hoursAndMinutes(total);
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours} hour${hours === 1 ? "" : "s"}`);
  if (minutes > 0) parts.push(`${minutes} minute${minutes === 1 ? "" : "s"}`);
  return parts.join(" and ");
}

/** Compact form for chips: "18h 42m", "42m", "2h", or "<1m". */
export function formatDurationShort(seconds: number): string {
  const total = Math.max(0, Math.floor(seconds || 0));
  if (total < 60) return "<1m";
  const { hours, minutes } = hoursAndMinutes(total);
  const parts: string[] = [];
  if (hours > 0) parts.push(`${hours}h`);
  if (minutes > 0) parts.push(`${minutes}m`);
  return parts.join(" ");
}
