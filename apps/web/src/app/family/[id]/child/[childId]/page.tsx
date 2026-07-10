"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken, mediaUrl, VaultItemOut } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

const TYPE_ICONS: Record<string, string> = {
  photo: "📷",
  video: "🎬",
  voice: "🎙️",
  message: "💬",
  document: "📄",
  achievement: "🏆",
};

export default function ChildVaultPage() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  const [items, setItems] = useState<VaultItemOut[] | null>(null);
  const [childName, setChildName] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [vault, family] = await Promise.all([
        api.listVault(childId),
        api.familyDetail(familyId),
      ]);
      setItems(vault);
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load this vault");
    }
  }, [childId, familyId, router]);

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
    <div className="space-y-8">
      <div>
        <a href={`/family/${familyId}`} className="text-sm text-stone-500 underline">
          ← Back to the family
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">
          {childName ? `${childName}'s vault` : "Vault"} 🌱
        </h1>
        <p className="text-stone-600">
          Every memory added here stays with {childName || "them"} for life.
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <MilestoneForm childId={childId} onPosted={load} childName={childName} />
        <MemoryForm childId={childId} onAdded={load} childName={childName} />
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-stone-800">Memories & milestones</h2>
        {items.length === 0 && (
          <p className="text-stone-600">
            The vault is empty — share the first memory above.
          </p>
        )}
        <div className="space-y-3">
          {items.map((item) => (
            <Card key={item.id} className="flex items-start gap-4">
              <span className="text-2xl">{TYPE_ICONS[item.type] ?? "✨"}</span>
              <div className="min-w-0 flex-1">
                <h3 className="font-semibold text-stone-900">{item.title}</h3>
                {item.body && <p className="mt-1 text-sm text-stone-600">{item.body}</p>}
                {item.media_id && item.media_content_type?.startsWith("image/") && (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={mediaUrl(item.media_id)}
                    alt={item.title}
                    className="mt-3 max-h-72 rounded-xl object-cover"
                  />
                )}
                <p className="mt-2 text-xs text-stone-400">
                  Added by {item.created_by_name} ·{" "}
                  {new Date(item.created_at).toLocaleDateString()}
                </p>
              </div>
            </Card>
          ))}
        </div>
      </section>
    </div>
  );
}

function MilestoneForm({
  childId,
  childName,
  onPosted,
}: {
  childId: string;
  childName: string;
  onPosted: () => void;
}) {
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
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
      await api.postMilestone(childId, { title, description: description || undefined, media_id });
      setTitle("");
      setDescription("");
      if (fileRef.current) fileRef.current.value = "";
      onPosted();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-1 font-semibold text-emerald-900">🎉 Celebrate a milestone</h3>
      <p className="mb-4 text-sm text-stone-500">
        The whole family gets the good news by email.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="mtitle">What happened?</Label>
          <Input
            id="mtitle"
            placeholder={`e.g. ${childName || "Emma"}'s first piano recital`}
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="mdesc">Tell the story (optional)</Label>
          <Input
            id="mdesc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="mphoto">Add a photo (optional)</Label>
          <input id="mphoto" ref={fileRef} type="file" accept="image/*" className="text-sm" />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Sharing…" : "Share the news"}
        </Button>
      </form>
    </Card>
  );
}

function MemoryForm({
  childId,
  childName,
  onAdded,
}: {
  childId: string;
  childName: string;
  onAdded: () => void;
}) {
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
      const media_id = file ? await api.uploadMedia(childId, file) : undefined;
      await api.addVaultItem(childId, {
        type: file ? "photo" : "message",
        title,
        body: body || undefined,
        media_id,
      });
      setTitle("");
      setBody("");
      if (fileRef.current) fileRef.current.value = "";
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-1 font-semibold text-emerald-900">📷 Add a memory</h3>
      <p className="mb-4 text-sm text-stone-500">
        A photo or a note for {childName || "them"} to treasure later.
      </p>
      <form onSubmit={submit} className="space-y-3">
        <div>
          <Label htmlFor="vtitle">Title</Label>
          <Input
            id="vtitle"
            placeholder="e.g. Sunday at the lake"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="vbody">A few words (optional)</Label>
          <Input id="vbody" value={body} onChange={(e) => setBody(e.target.value)} />
        </div>
        <div>
          <Label htmlFor="vphoto">Photo (optional)</Label>
          <input id="vphoto" ref={fileRef} type="file" accept="image/*" className="text-sm" />
        </div>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy} variant="soft" className="w-full">
          {busy ? "Saving…" : "Save to the vault"}
        </Button>
      </form>
    </Card>
  );
}
