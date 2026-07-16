"use client";

import { FamilyPlan } from "@/lib/api";

/** The one shared plan badge (copy deck §1/§3.6): "Premium" is a warm amber
 * pill, "Free" a quiet neutral one. One word each, no icons, no lock glyphs. */
export function PremiumPill({
  plan,
  tooltip,
  className = "",
}: {
  plan: FamilyPlan;
  tooltip?: string;
  className?: string;
}) {
  if (plan === "premium") {
    return (
      <span
        title={tooltip}
        className={`inline-flex items-center rounded-full bg-gradient-to-r from-amber-100 to-amber-50 px-2.5 py-0.5 text-xs font-semibold text-amber-900 ring-1 ring-amber-200 ${className}`}
      >
        Premium
      </span>
    );
  }
  return (
    <span
      title={tooltip}
      className={`inline-flex items-center rounded-full bg-stone-100 px-2.5 py-0.5 text-xs font-medium text-stone-500 ${className}`}
    >
      Free
    </span>
  );
}
