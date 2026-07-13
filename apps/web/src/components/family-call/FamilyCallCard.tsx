"use client";

import { useRef, useState } from "react";
import {
  api,
  ApiError,
  CallJoin,
  CallParticipant,
  CallState,
  ChildOut,
  mediaUrl,
} from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label, Modal } from "@/components/ui";
import { WhoIsHereModal } from "./WhoIsHereModal";
import { FamilyCallLayer } from "./FamilyCallLayer";

type Phase = "idle" | "picking" | "in-call";

export function FamilyCallCard({
  familyId,
  familyName,
  children,
  state,
  onRefresh,
}: {
  familyId: string;
  familyName: string;
  children: ChildOut[];
  state: CallState | null;
  onRefresh: () => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  const [join, setJoin] = useState<CallJoin | null>(null);
  const [busy, setBusy] = useState(false);
  const [joinError, setJoinError] = useState("");
  const launchRef = useRef<HTMLButtonElement>(null);

  const active = !!state?.active;

  function launch() {
    setJoinError("");
    if (children.length === 0) {
      void doJoin([]);
    } else {
      setPhase("picking");
    }
  }

  async function doJoin(childIds: string[]) {
    setBusy(true);
    setJoinError("");
    try {
      const j = await api.joinCall(familyId);
      if (childIds.length > 0) {
        try {
          await api.setChildrenPresent(familyId, childIds);
        } catch {
          // Marking who's present is a nice-to-have; don't block the call.
        }
      }
      setJoin(j);
      setPhase("in-call");
    } catch (err) {
      setJoinError(
        err instanceof ApiError ? err.message : "We couldn't start the call just now. Please try again."
      );
      setPhase("idle");
    } finally {
      setBusy(false);
    }
  }

  function closeLayer() {
    setPhase("idle");
    setJoin(null);
    onRefresh();
    // Return focus to the button that opened the call.
    setTimeout(() => launchRef.current?.focus(), 0);
  }

  return (
    <>
      {active ? (
        <LiveCard
          participants={state!.participants}
          childrenPresent={state!.children_present}
          onJoin={launch}
          busy={busy}
          launchRef={launchRef}
        />
      ) : (
        <IdleCard onStart={launch} busy={busy} launchRef={launchRef} />
      )}

      {joinError && (
        <div className="mt-2">
          <ErrorNote>{joinError}</ErrorNote>
        </div>
      )}

      <div className="mt-3">
        <PlannedCallSection familyId={familyId} state={state} onRefresh={onRefresh} />
      </div>

      <WhoIsHereModal
        open={phase === "picking"}
        children={children}
        busy={busy}
        error={joinError}
        onConfirm={doJoin}
        onCancel={() => setPhase("idle")}
      />

      {phase === "in-call" && join && (
        <FamilyCallLayer
          familyId={familyId}
          familyName={familyName}
          join={join}
          onClose={closeLayer}
        />
      )}
    </>
  );
}

function IdleCard({
  onStart,
  busy,
  launchRef,
}: {
  onStart: () => void;
  busy: boolean;
  launchRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <Card className="bg-gradient-to-br from-emerald-50 to-amber-50">
      <div className="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-center">
        <div>
          <h2 className="text-xl font-bold text-emerald-900">Gather the family in the living room</h2>
          <p className="mt-1 text-stone-600">
            Start a family call and see everyone&apos;s faces, wherever they are.
          </p>
        </div>
        <Button ref={launchRef} onClick={onStart} disabled={busy} className="w-full sm:w-auto">
          {busy ? "Starting…" : "Start a family call"}
        </Button>
      </div>
    </Card>
  );
}

function LiveCard({
  participants,
  childrenPresent,
  onJoin,
  busy,
  launchRef,
}: {
  participants: CallParticipant[];
  childrenPresent: CallState["children_present"];
  onJoin: () => void;
  busy: boolean;
  launchRef: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <Card className="bg-gradient-to-br from-emerald-50 to-white ring-2 ring-emerald-400">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <span className="inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900">
            <span
              aria-hidden
              className="h-2 w-2 rounded-full bg-amber-500 motion-safe:animate-pulse"
            />
            Live now
          </span>
          <div className="mt-3 flex items-center gap-3">
            <AvatarStack participants={participants} />
            <p className="text-lg font-medium text-stone-800">{summarize(participants)}</p>
          </div>
          {childrenPresent.length > 0 && (
            <div className="mt-3 flex flex-wrap gap-2">
              {childrenPresent.map((c) => (
                <span
                  key={c.child_id}
                  className="rounded-full bg-emerald-100 px-3 py-1 text-sm text-emerald-900"
                >
                  {c.first_name} is here too
                </span>
              ))}
            </div>
          )}
        </div>
        <Button ref={launchRef} onClick={onJoin} disabled={busy} className="w-full shrink-0 sm:w-auto">
          {busy ? "Joining…" : "Join the call happening now"}
        </Button>
      </div>
    </Card>
  );
}

function AvatarStack({ participants }: { participants: CallParticipant[] }) {
  const shown = participants.slice(0, 5);
  const extra = participants.length - shown.length;
  return (
    <div className="flex -space-x-3">
      {shown.map((p) => (
        <span key={p.user_id} className="inline-block">
          {p.avatar_media_id ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={mediaUrl(p.avatar_media_id)}
              alt=""
              className="h-11 w-11 rounded-full border-2 border-white object-cover"
            />
          ) : (
            <span className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-white bg-emerald-200 text-base font-semibold text-emerald-800">
              {p.display_name.charAt(0).toUpperCase()}
            </span>
          )}
        </span>
      ))}
      {extra > 0 && (
        <span className="flex h-11 w-11 items-center justify-center rounded-full border-2 border-white bg-stone-200 text-sm font-semibold text-stone-700">
          +{extra}
        </span>
      )}
    </div>
  );
}

function summarize(participants: CallParticipant[]): string {
  const names = participants.map((p) => (p.is_you ? "You" : p.display_name));
  const n = names.length;
  if (n === 0) return "The family call is starting.";
  if (n === 1) return `${names[0]} ${names[0] === "You" ? "are" : "is"} on the call now.`;
  if (n === 2) return `${names[0]} and ${names[1]} are on the call now.`;
  return `${names[0]}, ${names[1]} and ${n - 2} ${n - 2 === 1 ? "other" : "others"} are on the call now.`;
}

// --- Next family call ---

function PlannedCallSection({
  familyId,
  state,
  onRefresh,
}: {
  familyId: string;
  state: CallState | null;
  onRefresh: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const planned = state?.planned_call ?? null;

  async function clear() {
    setBusy(true);
    try {
      await api.clearPlannedCall(familyId);
      onRefresh();
    } catch {
      /* leave as-is; the poll will re-sync */
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-2xl border border-stone-200 bg-white/60 px-4 py-3">
      {planned ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-sm font-semibold text-stone-700">Next family call</p>
            <p className="text-stone-800">{formatWhen(planned.scheduled_for)}</p>
            {planned.note && <p className="text-sm text-stone-600">{planned.note}</p>}
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setOpen(true)}
              className="rounded-lg px-3 py-2 text-sm font-medium text-emerald-800 hover:bg-emerald-50"
            >
              Change
            </button>
            <button
              onClick={clear}
              disabled={busy}
              className="rounded-lg px-3 py-2 text-sm font-medium text-stone-500 hover:bg-stone-100 disabled:opacity-50"
            >
              Clear
            </button>
          </div>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="text-sm font-medium text-emerald-800 hover:text-emerald-900"
        >
          + Set the next call
        </button>
      )}

      <PlannedCallModal
        open={open}
        familyId={familyId}
        initial={planned}
        onClose={() => setOpen(false)}
        onSaved={() => {
          setOpen(false);
          onRefresh();
        }}
      />
    </div>
  );
}

function PlannedCallModal({
  open,
  familyId,
  initial,
  onClose,
  onSaved,
}: {
  open: boolean;
  familyId: string;
  initial: CallState["planned_call"];
  onClose: () => void;
  onSaved: () => void;
}) {
  const [when, setWhen] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [seeded, setSeeded] = useState(false);

  // Seed the fields from the existing plan the first render the modal is open.
  if (open && !seeded) {
    setWhen(initial ? toLocalInput(initial.scheduled_for) : "");
    setNote(initial?.note ?? "");
    setSeeded(true);
  }
  if (!open && seeded) setSeeded(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (!when) return;
    setBusy(true);
    setError("");
    try {
      await api.setPlannedCall(familyId, new Date(when).toISOString(), note.trim() || undefined);
      onSaved();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't save that. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Modal open={open} onClose={onClose} title="When's the next family call?">
      <form onSubmit={save} className="space-y-4">
        <div>
          <Label htmlFor="planned-when">Day and time</Label>
          <Input
            id="planned-when"
            type="datetime-local"
            value={when}
            onChange={(e) => setWhen(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="planned-note">A note for the family (optional)</Label>
          <Input
            id="planned-note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder="Sunday catch-up with Grandma"
          />
        </div>
        {error && <ErrorNote>{error}</ErrorNote>}
        <div className="flex flex-col gap-2">
          <Button type="submit" disabled={busy || !when}>
            {busy ? "Saving…" : "Save the next call"}
          </Button>
          <Button type="button" variant="soft" onClick={onClose}>
            Never mind
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function formatWhen(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** ISO string -> value a <input type="datetime-local"> accepts (local time). */
function toLocalInput(iso: string): string {
  const d = new Date(iso);
  const off = d.getTimezoneOffset();
  const local = new Date(d.getTime() - off * 60000);
  return local.toISOString().slice(0, 16);
}
