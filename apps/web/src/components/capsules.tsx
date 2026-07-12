"use client";

import { useRef, useState } from "react";
import { api, ApiError, CapsuleOut, mediaUrl, ReleaseCondition } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

function conditionLabel(c: CapsuleOut): string {
  switch (c.release_condition) {
    case "age":
      return `Opens when they turn ${c.release_age}`;
    case "date":
      return `Opens ${new Date(c.release_date + "T00:00:00").toLocaleDateString()}`;
    case "milestone":
      return `Opens at: ${c.release_milestone}`;
  }
}

export function CapsulesSection({
  childId,
  childName,
  capsules,
  isParent,
  onChanged,
}: {
  childId: string;
  childName: string;
  capsules: CapsuleOut[];
  isParent: boolean;
  onChanged: () => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  async function release(capsuleId: string) {
    setError("");
    try {
      await api.releaseCapsule(capsuleId);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-stone-800">Time capsules</h2>
        <Button variant="soft" onClick={() => setShowForm((v) => !v)}>
          {showForm ? "Close" : "✉️ Seal a capsule"}
        </Button>
      </div>
      <ErrorNote>{error}</ErrorNote>

      {showForm && (
        <CapsuleForm
          childId={childId}
          childName={childName}
          onSealed={() => {
            setShowForm(false);
            onChanged();
          }}
        />
      )}

      {capsules.length === 0 && !showForm && (
        <p className="text-stone-600">
          Seal a letter or recording today. {childName || "They"} will open it years from
          now, right when it matters most.
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        {capsules.map((c) =>
          c.status === "sealed" ? (
            <Card key={c.id} className="border-dashed bg-stone-50">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="font-semibold text-stone-700">🔒 Sealed capsule</h3>
                  <p className="mt-1 text-sm text-stone-500">
                    From {c.is_mine ? "you" : c.created_by_name} · {conditionLabel(c)}
                  </p>
                  {c.is_mine && c.body && (
                    <p className="mt-2 line-clamp-2 text-sm italic text-stone-400">
                      “{c.body}”
                    </p>
                  )}
                </div>
                {c.release_condition === "milestone" && (c.is_mine || isParent) && (
                  <Button variant="soft" onClick={() => release(c.id)}>
                    Open now
                  </Button>
                )}
              </div>
            </Card>
          ) : (
            <Card key={c.id} className="bg-amber-50/40">
              <h3 className="font-semibold text-amber-900">💌 From {c.created_by_name}</h3>
              {c.body && <p className="mt-2 whitespace-pre-wrap text-stone-700">{c.body}</p>}
              {c.media_id && c.media_content_type?.startsWith("image/") && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(c.media_id)}
                  alt={`Time capsule from ${c.created_by_name}`}
                  className="mt-3 max-h-72 rounded-xl object-cover"
                />
              )}
              {c.media_id && c.media_content_type?.startsWith("audio/") && (
                <audio controls src={mediaUrl(c.media_id)} className="mt-3 w-full" />
              )}
              {c.media_id && c.media_content_type?.startsWith("video/") && (
                <video controls src={mediaUrl(c.media_id)} className="mt-3 max-h-72 rounded-xl" />
              )}
              <p className="mt-2 text-xs text-stone-400">
                Sealed {new Date(c.created_at).toLocaleDateString()} · opened{" "}
                {c.released_at ? new Date(c.released_at).toLocaleDateString() : ""}
              </p>
            </Card>
          )
        )}
      </div>
    </section>
  );
}

function CapsuleForm({
  childId,
  childName,
  onSealed,
}: {
  childId: string;
  childName: string;
  onSealed: () => void;
}) {
  const [body, setBody] = useState("");
  const [condition, setCondition] = useState<ReleaseCondition>("age");
  const [age, setAge] = useState("18");
  const [dateValue, setDateValue] = useState("");
  const [milestone, setMilestone] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const file = fileRef.current?.files?.[0];
      const media_id = file ? await api.uploadMedia(childId, file) : undefined;
      const type = file
        ? file.type.startsWith("video/")
          ? "video"
          : file.type.startsWith("audio/")
            ? "audio"
            : "letter"
        : "letter";
      await api.createCapsule(childId, {
        type,
        body: body || undefined,
        media_id,
        release_condition: condition,
        release_age: condition === "age" ? parseInt(age, 10) : undefined,
        release_date: condition === "date" ? dateValue : undefined,
        release_milestone: condition === "milestone" ? milestone : undefined,
      });
      onSealed();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-1 font-semibold text-emerald-900">✉️ A message for the future</h3>
      <p className="mb-4 text-sm text-stone-500">
        Only you can see it until the day it opens.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="cbody">Your letter to {childName || "them"}</Label>
          <textarea
            id="cbody"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={4}
            className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none"
            placeholder="Dear Emma, today you..."
          />
        </div>
        <div>
          <Label htmlFor="cmedia">Or attach a photo, voice note, or video (optional)</Label>
          <input
            id="cmedia"
            ref={fileRef}
            type="file"
            accept="image/*,audio/*,video/*"
            className="text-sm"
          />
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="ccondition">When should it open?</Label>
            <select
              id="ccondition"
              value={condition}
              onChange={(e) => setCondition(e.target.value as ReleaseCondition)}
              className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base"
            >
              <option value="age">At an age</option>
              <option value="date">On a date</option>
              <option value="milestone">At a life moment</option>
            </select>
          </div>
          <div>
            {condition === "age" && (
              <>
                <Label htmlFor="cage">Their age</Label>
                <Input
                  id="cage"
                  type="number"
                  min="1"
                  max="120"
                  value={age}
                  onChange={(e) => setAge(e.target.value)}
                  required
                />
              </>
            )}
            {condition === "date" && (
              <>
                <Label htmlFor="cdate">The date</Label>
                <Input
                  id="cdate"
                  type="date"
                  value={dateValue}
                  onChange={(e) => setDateValue(e.target.value)}
                  required
                />
              </>
            )}
            {condition === "milestone" && (
              <>
                <Label htmlFor="cmilestone">The moment</Label>
                <Input
                  id="cmilestone"
                  placeholder="e.g. Graduation day"
                  value={milestone}
                  onChange={(e) => setMilestone(e.target.value)}
                  required
                />
              </>
            )}
          </div>
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Sealing…" : "Seal it for the future"}
        </Button>
      </form>
    </Card>
  );
}
