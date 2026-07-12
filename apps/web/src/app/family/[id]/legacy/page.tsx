"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken, LegacyOut, LegacyType, mediaUrl } from "@/lib/api";
import { familyPhrase } from "@/lib/text";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

const TYPE_META: Record<LegacyType, { icon: string; label: string; prompt: string }> = {
  story: { icon: "📖", label: "Story", prompt: "Tell a story from the old days" },
  recipe: { icon: "🥧", label: "Recipe", prompt: "Pass down a family recipe" },
  wisdom: { icon: "🦉", label: "Wisdom", prompt: "Record a piece of advice" },
  photo: { icon: "🖼️", label: "Photo", prompt: "Add a cherished old photo" },
  document: { icon: "📜", label: "Document", prompt: "Keep an important document safe" },
};

const TYPE_ORDER: LegacyType[] = ["story", "recipe", "wisdom", "photo", "document"];

export default function LegacyPage() {
  const router = useRouter();
  const { id: familyId } = useParams<{ id: string }>();
  const [items, setItems] = useState<LegacyOut[] | null>(null);
  const [familyName, setFamilyName] = useState("");
  const [error, setError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [presetType, setPresetType] = useState<LegacyType>("story");
  const autoOpened = useRef(false);

  const load = useCallback(async () => {
    try {
      const [legacy, family] = await Promise.all([
        api.listLegacy(familyId),
        api.familyDetail(familyId),
      ]);
      setItems(legacy);
      setFamilyName(family.name);
      // First visit with an empty archive: open the form so it's inviting, not blank
      if (legacy.length === 0 && !autoOpened.current) {
        autoOpened.current = true;
        setShowForm(true);
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load the archive");
    }
  }, [familyId, router]);

  function startAdd(type: LegacyType) {
    setPresetType(type);
    setShowForm(true);
  }

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
                ? `The story of ${familyPhrase(familyName)}.`
                : "Your family story."}{" "}
              Recipes, wisdom, and history, kept for every generation.
            </p>
          </div>
          <Button onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Close" : "+ Add"}
          </Button>
        </div>
      </div>

      {showForm && (
        <LegacyForm
          key={presetType}
          familyId={familyId}
          initialType={presetType}
          onAdded={() => {
            setShowForm(false);
            load();
          }}
        />
      )}

      {/* Inspiration prompts: one tap opens the form pre-set to that kind. Shown
          prominently when the archive is empty, as a quiet strip once it has items. */}
      {items.length === 0 ? (
        <Card className="bg-gradient-to-br from-emerald-50 to-blue-50">
          <div className="text-center">
            <div className="text-4xl">🌳</div>
            <h2 className="mt-2 text-xl font-bold text-emerald-900">
              Every family has a story. Start yours.
            </h2>
            <p className="mx-auto mt-1 max-w-md text-sm text-stone-600">
              The archive holds the things worth keeping for generations: recipes in a
              grandparent&apos;s words, the stories behind old photos, the advice you never
              want lost. Add the first one below, or pick a place to begin.
            </p>
          </div>
          <div className="mt-5 grid gap-2 sm:grid-cols-2">
            {TYPE_ORDER.map((t) => (
              <button
                key={t}
                onClick={() => startAdd(t)}
                className="flex items-center gap-3 rounded-xl border border-stone-200 bg-white/70 px-4 py-3 text-left transition hover:border-emerald-400 hover:bg-white"
              >
                <span className="text-2xl">{TYPE_META[t].icon}</span>
                <span className="text-sm font-medium text-stone-800">{TYPE_META[t].prompt}</span>
              </button>
            ))}
          </div>
        </Card>
      ) : (
        <div className="flex flex-wrap gap-2">
          {TYPE_ORDER.map((t) => (
            <button
              key={t}
              onClick={() => startAdd(t)}
              className="inline-flex items-center gap-1.5 rounded-full border border-stone-200 px-3 py-1.5 text-sm text-stone-600 hover:border-emerald-400 hover:text-emerald-800"
            >
              <span>{TYPE_META[t].icon}</span> Add {TYPE_META[t].label.toLowerCase()}
            </button>
          ))}
        </div>
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

function LegacyForm({
  familyId,
  onAdded,
  initialType = "story",
}: {
  familyId: string;
  onAdded: () => void;
  initialType?: LegacyType;
}) {
  const [type, setType] = useState<LegacyType>(initialType);
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
