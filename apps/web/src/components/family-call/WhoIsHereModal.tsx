"use client";

import { useEffect, useState } from "react";
import { ChildOut, mediaUrl } from "@/lib/api";
import { Button, ErrorNote, Modal } from "@/components/ui";

/**
 * Shown right after someone taps Start/Join, before the call opens. Lets the
 * grownup say which little ones are in the room with them so the rest of the
 * family knows who is there. Kept to one tap: pick faces, then join.
 */
export function WhoIsHereModal({
  open,
  children,
  busy,
  error,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  children: ChildOut[];
  busy: boolean;
  error: string;
  /** childIds of the little ones present (empty = just me). */
  onConfirm: (childIds: string[]) => void;
  onCancel: () => void;
}) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Start fresh each time the picker opens.
  useEffect(() => {
    if (open) setSelected(new Set());
  }, [open]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const count = selected.size;
  const joinLabel = busy
    ? "Joining…"
    : count === 0
      ? "Join the call"
      : count === 1
        ? "Join the call with 1 little one"
        : `Join the call with ${count} little ones`;

  return (
    <Modal open={open} onClose={busy ? () => {} : onCancel} title="Who's here with you?">
      <p className="-mt-2 mb-4 text-sm text-stone-600">
        Tap everyone who is in the room with you, so the rest of the family knows who they&apos;ll
        see.
      </p>

      <div className="grid grid-cols-3 gap-3 sm:grid-cols-4">
        {children.map((c) => {
          const on = selected.has(c.id);
          return (
            <button
              key={c.id}
              type="button"
              onClick={() => toggle(c.id)}
              aria-pressed={on}
              className={`flex flex-col items-center gap-2 rounded-2xl border-2 p-2 transition ${
                on
                  ? "border-emerald-600 bg-emerald-50"
                  : "border-stone-200 bg-white hover:border-emerald-300"
              }`}
            >
              <span className="relative">
                {c.avatar_media_id ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(c.avatar_media_id)}
                    alt=""
                    className="h-16 w-16 rounded-full object-cover"
                  />
                ) : (
                  <span className="flex h-16 w-16 items-center justify-center rounded-full bg-emerald-100 text-2xl font-semibold text-emerald-800">
                    {c.first_name.charAt(0).toUpperCase()}
                  </span>
                )}
                {on && (
                  <span
                    aria-hidden
                    className="absolute -bottom-1 -right-1 flex h-6 w-6 items-center justify-center rounded-full bg-emerald-600 text-sm text-white shadow"
                  >
                    ✓
                  </span>
                )}
              </span>
              <span className="text-sm font-medium text-stone-800">{c.first_name}</span>
              <span className="sr-only">{on ? "is here" : "not here"}</span>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="mt-4">
          <ErrorNote>{error}</ErrorNote>
        </div>
      )}

      <div className="mt-6 flex flex-col gap-2">
        <Button onClick={() => onConfirm(Array.from(selected))} disabled={busy}>
          {joinLabel}
        </Button>
        <Button variant="soft" onClick={() => onConfirm([])} disabled={busy}>
          Just me for now
        </Button>
      </div>
    </Modal>
  );
}
