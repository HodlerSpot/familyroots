"use client";

import { FamilyRole } from "@/lib/api";
import { Modal } from "@/components/ui";

/* All strings verbatim from docs/brand/premium-copy.md §3.4 (final copy deck). */
const CAPABILITY_COPY: Record<string, { title: string; body: string }> = {
  video_upload: {
    title: "Videos are part of FutureRoots Premium",
    body: "Photos and voice notes are always free. Premium adds video memories and family video calls for the whole family, $9.99 a month or $99 a year.",
  },
  family_video_call: {
    title: "Family video calls are part of Premium",
    body: "See everyone's faces, from anywhere. One membership covers the whole family, $9.99 a month or $99 a year.",
  },
};

const DEFAULT_COPY = {
  title: "This is part of FutureRoots Premium.",
  body: "More room for your family's story. One membership covers everyone.",
};

const NON_PARENT_HELPER = "Or mention it to a parent. Upgrading takes about a minute.";

const PRIMARY_LINK_CLASS =
  "inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800";

/** The single shared upsell, rendered inline (e.g. inside an upload form).
 * An invitation, never a wall: parents get Upgrade, everyone else can gift. */
export function PremiumUpsellCard({
  familyId,
  capability,
  role,
  onDismiss,
}: {
  familyId: string;
  capability: string;
  role: FamilyRole | null;
  onDismiss?: () => void;
}) {
  const copy = CAPABILITY_COPY[capability] ?? DEFAULT_COPY;
  const isParent = role === "parent";
  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
      <div className="flex items-start gap-3">
        <span aria-hidden className="text-2xl">
          ✨
        </span>
        <div className="min-w-0">
          <h4 className="font-semibold text-amber-950">{copy.title}</h4>
          <p className="mt-1 text-sm text-stone-600">{copy.body}</p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {isParent ? (
              <a href={`/family/${familyId}/premium`} className={PRIMARY_LINK_CLASS}>
                Upgrade to Premium
              </a>
            ) : (
              <a href={`/family/${familyId}/premium/gift`} className={PRIMARY_LINK_CLASS}>
                Gift Premium to the family
              </a>
            )}
            {onDismiss && (
              <button
                type="button"
                onClick={onDismiss}
                className="rounded-lg px-4 py-3 text-base font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-700"
              >
                Maybe later
              </button>
            )}
          </div>
          {!isParent && <p className="mt-2 text-xs text-stone-500">{NON_PARENT_HELPER}</p>}
        </div>
      </div>
    </div>
  );
}

/** Modal flavor of the same upsell, used where the gated action is a button
 * (for example the family video call card). Closing it is the "Maybe later". */
export function PremiumUpsellModal({
  open,
  onClose,
  familyId,
  capability,
  role,
}: {
  open: boolean;
  onClose: () => void;
  familyId: string;
  capability: string;
  role: FamilyRole | null;
}) {
  const copy = CAPABILITY_COPY[capability] ?? DEFAULT_COPY;
  const isParent = role === "parent";
  return (
    <Modal open={open} onClose={onClose} title={copy.title}>
      <p className="text-stone-600">{copy.body}</p>
      <div className="mt-5 flex flex-col gap-2">
        {isParent ? (
          <a href={`/family/${familyId}/premium`} className={`${PRIMARY_LINK_CLASS} text-center`}>
            Upgrade to Premium
          </a>
        ) : (
          <a
            href={`/family/${familyId}/premium/gift`}
            className={`${PRIMARY_LINK_CLASS} text-center`}
          >
            Gift Premium to the family
          </a>
        )}
        <button
          type="button"
          onClick={onClose}
          className="rounded-lg px-4 py-3 text-base font-medium text-stone-500 hover:bg-stone-100 hover:text-stone-700"
        >
          Maybe later
        </button>
      </div>
      {!isParent && <p className="mt-3 text-xs text-stone-500">{NON_PARENT_HELPER}</p>}
    </Modal>
  );
}
