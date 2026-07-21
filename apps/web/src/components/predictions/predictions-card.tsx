"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, OpenRoundOut, PredictionGameOut, PredictionOut } from "@/lib/api";
import { Button, Card, ErrorNote, Input } from "@/components/ui";
import { WordCloud } from "./word-cloud";

const MAX_LEN = 120;
const MIN_LEN = 2;

function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

/** The seal line. A supporter's payload has `seals_on === null` (the API strips
 * the birthdate-derived date), so a null date IS the supporter signal — we
 * never reconstruct a date or countdown for them. */
function sealLine(name: string, sealsOn: string | null): string {
  const who = name || "them";
  if (!sealsOn) return `Seals on ${who}'s next birthday.`;
  const when = new Date(sealsOn + "T00:00:00").toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
  return `Seals on ${who}'s birthday, ${when}.`;
}

/** One row in the attributed list, with inline edit + a two-step remove for the
 * viewer's own predictions (and remove-only for parents/guardians moderating). */
function PredictionRow({
  pred,
  onChanged,
}: {
  pred: PredictionOut;
  onChanged: () => Promise<void>;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(pred.body);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = draft.trim();

  async function save(e: React.FormEvent) {
    e.preventDefault();
    if (trimmed.length < MIN_LEN || trimmed.length > MAX_LEN) {
      setError(`A prediction is ${MIN_LEN} to ${MAX_LEN} characters.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.editPrediction(pred.id, trimmed);
      setEditing(false);
      await onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't save that just now.");
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api.deletePrediction(pred.id);
      await onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't remove that just now.");
      setBusy(false);
      setConfirming(false);
    }
  }

  if (editing) {
    return (
      <li className="rounded-xl bg-stone-50 px-3 py-2">
        <form onSubmit={save} className="space-y-2">
          <Input
            value={draft}
            maxLength={MAX_LEN}
            onChange={(e) => setDraft(e.target.value)}
            aria-label="Edit your prediction"
            autoFocus
          />
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs tabular-nums text-stone-400">
              {draft.length}/{MAX_LEN}
            </span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => {
                  setEditing(false);
                  setDraft(pred.body);
                  setError("");
                }}
                className="text-sm text-stone-500 hover:text-stone-700"
              >
                Cancel
              </button>
              <Button type="submit" variant="soft" disabled={busy || trimmed.length < MIN_LEN}>
                {busy ? "Saving…" : "Save"}
              </Button>
            </div>
          </div>
          <ErrorNote>{error}</ErrorNote>
        </form>
      </li>
    );
  }

  return (
    <li className="rounded-xl bg-stone-50 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-stone-900">
          {pred.author_name}
          {pred.is_mine && <span className="ml-1 font-normal text-emerald-700">(you)</span>}
        </span>
        <span className="shrink-0 text-xs text-stone-400">{timeAgo(pred.created_at)}</span>
      </div>
      <p className="mt-0.5 whitespace-pre-wrap text-stone-700">{pred.body}</p>
      {pred.can_delete && (
        <div className="mt-2 flex items-center gap-3">
          {pred.is_mine && (
            <button
              type="button"
              onClick={() => setEditing(true)}
              disabled={busy}
              className="text-xs font-medium text-emerald-700 hover:text-emerald-900 disabled:opacity-50"
            >
              Edit
            </button>
          )}
          {confirming ? (
            <span className="flex items-center gap-2 text-xs text-stone-500">
              Remove this?
              <button
                type="button"
                onClick={remove}
                disabled={busy}
                className="font-medium text-red-600 hover:text-red-700 disabled:opacity-50"
              >
                {busy ? "Removing…" : "Yes, remove"}
              </button>
              <button
                type="button"
                onClick={() => setConfirming(false)}
                disabled={busy}
                className="text-stone-500 hover:text-stone-700"
              >
                Keep
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => setConfirming(true)}
              disabled={busy}
              className="text-xs text-stone-400 hover:text-red-600 disabled:opacity-50"
            >
              Remove
            </button>
          )}
        </div>
      )}
      <ErrorNote>{error}</ErrorNote>
    </li>
  );
}

/** The add field. Hidden by the card once the caller has used all their slots. */
function Composer({
  childName,
  onAdd,
}: {
  childName: string;
  onAdd: (body: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = draft.trim();
  const tooLong = draft.length > MAX_LEN;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (trimmed.length < MIN_LEN || tooLong) return;
    setBusy(true);
    setError("");
    try {
      await onAdd(trimmed);
      setDraft("");
    } catch (err) {
      // The 4th add returns a warm 409 ("You've added all 3…") — surface it as-is.
      setError(err instanceof ApiError ? err.message : "We couldn't add that just now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="space-y-2">
      <Input
        value={draft}
        maxLength={MAX_LEN}
        onChange={(e) => setDraft(e.target.value)}
        placeholder={`What will ${childName || "they"} grow up to do?`}
        aria-label="Add a prediction"
      />
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs tabular-nums text-stone-400">
          {draft.length}/{MAX_LEN}
        </span>
        <Button type="submit" disabled={busy || trimmed.length < MIN_LEN}>
          {busy ? "Adding…" : "Add your prediction"}
        </Button>
      </div>
      <ErrorNote>{error}</ErrorNote>
    </form>
  );
}

/** The child-page card: the live cloud, the composer with remaining-slot count,
 * the attributed list, and the warm seal banner. Renders nothing when there is
 * no open round to show and the book is not yet open. All role/date behaviour
 * comes from the API payload (supporters get `seals_on === null` and
 * `completed === false`), never from client-side reconstruction. */
export function PredictionsCard({
  familyId,
  childId,
  childName,
}: {
  familyId: string;
  childId: string;
  childName: string;
}) {
  const [game, setGame] = useState<PredictionGameOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const g = await api.getPredictionGame(childId);
    setGame(g);
  }, [childId]);

  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const g = await api.getPredictionGame(childId);
        if (active) setGame(g);
      } catch (err) {
        if (active) setError(err instanceof ApiError ? err.message : "Couldn't load predictions");
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => {
      active = false;
    };
  }, [childId]);

  const addPrediction = useCallback(
    async (body: string) => {
      await api.addPrediction(childId, body);
      // Refetch so the server-computed cloud, list, and slot count stay exact.
      await refresh();
    },
    [childId, refresh]
  );

  // Stay quiet while loading or when there is genuinely nothing to show
  // (a supporter with no open round, or a child who has aged out).
  if (loading) return null;
  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!game) return null;

  const name = game.child_first_name || childName;

  // The book has released: a warm link, no game surface. (Family only — a
  // supporter always gets completed=false, so they never see this.)
  if (game.round === null) {
    if (!game.completed) return null;
    return (
      <Card className="border-emerald-200 bg-emerald-50/60">
        <h3 className="font-semibold text-emerald-900">📖 {name}&apos;s Book of Predictions is open</h3>
        <p className="mt-1 text-sm text-stone-600">
          Years of the family imagining who {name || "they"} would become, all in one place.
        </p>
        <a
          href={`/family/${familyId}/child/${childId}/predictions`}
          className="mt-3 inline-block rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white hover:bg-emerald-800"
        >
          Open the book
        </a>
      </Card>
    );
  }

  const round: OpenRoundOut = game.round;
  const used = round.my_prediction_ids.length;
  const remaining = Math.max(0, round.max_per_member - used);

  return (
    <Card>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-lg font-semibold text-emerald-900">🔮 Predictions for {name}</h3>
        <span className="text-sm text-stone-500">{round.year}</span>
      </div>
      <p className="mt-1 text-sm text-stone-600">
        In a few words, what do you imagine for {name || "them"}? Everyone&apos;s guesses grow
        the cloud below. {sealLine(name, round.seals_on)}
      </p>

      <div className="mt-4 rounded-xl border border-stone-100 bg-stone-50/60 p-4">
        <WordCloud words={round.cloud} />
      </div>

      <div className="mt-4">
        {remaining > 0 ? (
          <>
            <p className="mb-2 text-sm text-stone-500">
              {used === 0
                ? `You can add up to ${round.max_per_member} predictions this year.`
                : `${remaining} more ${remaining === 1 ? "prediction" : "predictions"} to add this year.`}
            </p>
            <Composer childName={name} onAdd={addPrediction} />
          </>
        ) : (
          <p className="text-sm text-emerald-800">
            You&apos;ve added all {round.max_per_member} of your predictions for this year. You can
            still edit or remove them below until the round seals.
          </p>
        )}
      </div>

      {round.predictions.length > 0 && (
        <ul className="mt-4 space-y-2">
          {round.predictions.map((p) => (
            <PredictionRow key={p.id} pred={p} onChanged={refresh} />
          ))}
        </ul>
      )}
    </Card>
  );
}
