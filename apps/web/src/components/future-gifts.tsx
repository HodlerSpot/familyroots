"use client";

import { formatDurationLong, formatDurationShort } from "@/lib/text";

/**
 * "Future Gifts" — a warm estimate of how much meaningful time of memories,
 * stories, wisdom, and love the family has preserved for a child. The API sends
 * seconds only; all copy (the compact chip label and the full hover sentence) is
 * assembled here in FutureRoots voice.
 *
 * Treat `seconds` defensively: it is null for supporters and may be undefined on
 * older payloads. In both cases nothing renders.
 *
 * - `variant="compact"` — the child-card chip. Renders nothing at zero so cards
 *   stay uncluttered.
 * - `variant="full"` — the vault-header indicator. At zero it shows a gentle,
 *   encouraging line instead of a "0".
 */
export function FutureGifts({
  seconds,
  childName,
  variant = "compact",
  className = "",
}: {
  seconds: number | null | undefined;
  childName: string;
  variant?: "compact" | "full";
  className?: string;
}) {
  // Supporter (null) or not-yet-loaded (undefined): render nothing.
  if (seconds === null || seconds === undefined) return null;

  const name = childName?.trim() || "your child";
  const tooltip = `Your family has preserved ${formatDurationLong(
    seconds,
  )} of memories, stories, wisdom, and love for ${name}'s future.`;

  if (variant === "compact") {
    // Keep the card uncluttered: no chip until there is something to celebrate.
    if (seconds <= 0) return null;
    return (
      <span
        title={tooltip}
        className={`mt-1 inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-900 ${className}`}
      >
        <span aria-hidden>🎁</span>
        {formatDurationShort(seconds)}
      </span>
    );
  }

  // Full variant (vault header).
  if (seconds <= 0) {
    return (
      <p className={`mt-2 text-sm text-amber-800 ${className}`}>
        <span aria-hidden className="mr-1">
          🎁
        </span>
        Start preserving moments for {name}.
      </p>
    );
  }

  return (
    <div
      title={tooltip}
      className={`mt-2 inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-amber-100 to-amber-50 px-3 py-1 text-sm text-amber-900 ring-1 ring-amber-200 ${className}`}
    >
      <span aria-hidden className="text-base">
        🎁
      </span>
      <span>
        <span className="font-semibold">Future Gifts:</span>{" "}
        {formatDurationShort(seconds)} preserved
      </span>
    </div>
  );
}
