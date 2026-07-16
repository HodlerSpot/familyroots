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
