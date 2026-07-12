"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken, LegacyOut, LegacyType, mediaUrl } from "@/lib/api";
import { familyPhrase } from "@/lib/text";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

const TYPE_META: Record<LegacyType, { icon: string; label: string }> = {
  story: { icon: "📖", label: "Story" },
  recipe: { icon: "🥧", label: "Recipe" },
  document: { icon: "📜", label: "Document" },
  photo: { icon: "🖼️", label: "Photo" },
  wisdom: { icon: "🦉", label: "Wisdom" },
};

export default function LegacyPage() {
  const router = useRouter();
  const { id: familyId } = useParams<{ id: string }>();
  const [items, setItems] = useState<LegacyOut[] | null>(null);
  const [familyName, setFamilyName] = useState("");
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(async () => {
    try {
      const [legacy, family] = await Promise.all([
        api.listLegacy(familyId),
        api.familyDetail(familyId),
      ]);
      setItems(legacy);
      setFamilyName(family.name);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load the archive");
    }
  }, [familyId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (items === null) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <a href={`/family/${familyId}`} className="text-sm text-stone-500 underline">
          ← Back to the family
        </a>
        <div className="mt-2 flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-emerald-900">Legacy archive 🌳</h1>
            <p className="text-stone-600">
              {familyName
                ? `The story of ${familyPhrase(familyName)}`
                : "Your family story"}{" "}
              — recipes, wisdom, and history, kept for every generation.
            </p>
          </div>
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Close" : "+ Add"}
          </Button>
        </div>
      </div>

      {showForm && (
        <LegacyForm
          familyId={familyId}
          onAdded={() => {
            setShowForm(false);
            load();
          }}
        />
      )}

      {items.length === 0 && !showForm && (
        <p className="text-stone-600">
          The archive is waiting for its first treasure — a recipe, a story from the old
          days, a piece of advice worth keeping.
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {items.map((item) => (
          <Card key={item.id}>
            <div className="flex items-start gap-3">
              <span className="text-2xl">{TYPE_META[item.type].icon}</span>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-stone-900">{item.title}</h3>
                <p className="text-xs text-stone-400">
                  {TYPE_META[item.type].label} · from {item.created_by_name} ·{" "}
                  {new Date(item.created_at).toLocaleDateString()}
                </p>
                {item.body && (
                  <p className="mt-2 whitespace-pre-wrap text-sm text-stone-700">{item.body}</p>
                )}
                {item.media_id && item.media_content_type?.startsWith("image/") && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(item.media_id)}
                    alt={item.title}
                    className="mt-3 max-h-64 rounded-xl object-cover"
                  />
                )}
                {item.media_id && item.media_content_type?.startsWith("audio/") && (
                  <audio controls src={mediaUrl(item.media_id)} className="mt-3 w-full" />
                )}
                {item.media_id && item.media_content_type?.startsWith("video/") && (
                  <video
                    controls
                    src={mediaUrl(item.media_id)}
                    className="mt-3 max-h-64 rounded-xl"
                  />
                )}
              </div>
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}

function LegacyForm({ familyId, onAdded }: { familyId: string; onAdded: () => void }) {
  const [type, setType] = useState<LegacyType>("story");
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const file = fileRef.current?.files?.[0];
      const media_id = file ? await api.uploadFamilyMedia(familyId, file) : undefined;
      await api.addLegacy(familyId, {
        type,
        title,
        body: body || undefined,
        media_id,
      });
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <Card>
      <form onSubmit={submit} className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="ltype">What is it?</Label>
            <select
              id="ltype"
              value={type}
              onChange={(e) => setType(e.target.value as LegacyType)}
              className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base"
            >
              {Object.entries(TYPE_META).map(([value, meta]) => (
                <option key={value} value={value}>
                  {meta.icon} {meta.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <Label htmlFor="ltitle">Title</Label>
            <Input
              id="ltitle"
              placeholder="e.g. Grandma Rose's apple pie"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              required
            />
          </div>
        </div>
        <div>
          <Label htmlFor="lbody">The story itself</Label>
          <textarea
            id="lbody"
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={4}
            className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none"
            placeholder="How it was told to me..."
          />
        </div>
        <div>
          <Label htmlFor="lmedia">Photo, recording, or scan (optional)</Label>
          <input
            id="lmedia"
            ref={fileRef}
            type="file"
            accept="image/*,audio/*,video/*"
            className="text-sm"
          />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Add to the archive"}
        </Button>
      </form>
    </Card>
  );
}
