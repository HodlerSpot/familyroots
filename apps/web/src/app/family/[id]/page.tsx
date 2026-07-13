"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  ApiError,
  ChildOut,
  FamilyDetail,
  FamilyRole,
  FeedEventOut,
  getToken,
  mediaUrl,
} from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { FamilyFeedList } from "@/components/feed";

export default function FamilyPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [family, setFamily] = useState<FamilyDetail | null>(null);
  const [feed, setFeed] = useState<FeedEventOut[]>([]);
  const [myRole, setMyRole] = useState<FamilyRole | null>(null);
  const [error, setError] = useState("");

  // Supporters (coaches, mentors, friends) get a warm, view-only experience:
  // no legacy archive, no family administration. Everyone else sees the archive
  // and moments, but only parents/guardians manage the family (add children, invite).
  const isSupporter = myRole === "supporter";
  const canManage = myRole === "parent" || myRole === "guardian";

  const load = useCallback(async () => {
    try {
      const [detail, me, events] = await Promise.all([
        api.familyDetail(id),
        api.me(),
        api.familyFeed(id),
      ]);
      setFamily(detail);
      setMyRole(detail.members.find((m) => m.user.id === me.id)?.role ?? null);
      setFeed(events);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load this family");
    }
  }, [id, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!family) return <p className="text-stone-500">Loading…</p>;

  const latest = feed.slice(0, 3);

  return (
    <div className="space-y-8">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          ← All families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">{family.name}</h1>
      </div>

      <div className="grid gap-8 lg:grid-cols-[1.8fr,1fr]">
        {/* LEFT: the people in the family */}
        <div className="space-y-8">
          <section className="space-y-3">
            <h2 className="text-xl font-semibold text-stone-800">Children</h2>
            {family.children.length === 0 && (
              <p className="text-stone-600">No children added yet.</p>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              {family.children.map((c) => (
                <Card key={c.id} className="transition hover:border-emerald-400">
                  <a href={`/family/${family.id}/child/${c.id}`} className="flex items-center gap-3">
                    <ChildAvatar child={c} />
                    <div className="min-w-0">
                      <h3 className="text-lg font-semibold text-stone-900">{c.first_name}</h3>
                      {c.birthdate && (
                        <p className="text-sm text-stone-500">
                          Born {new Date(c.birthdate + "T00:00:00").toLocaleDateString()}
                        </p>
                      )}
                      <p className="mt-1 text-sm text-emerald-800">
                        Open {c.first_name}&apos;s vault →
                      </p>
                    </div>
                  </a>
                </Card>
              ))}
            </div>
            {canManage && (
              <AddChildForm
                familyId={family.id}
                onAdded={load}
                hasChildren={family.children.length > 0}
              />
            )}
          </section>

          <section className="space-y-3">
            <h2 className="text-xl font-semibold text-stone-800">Family members</h2>
            <Card>
              <ul className="divide-y divide-stone-100">
                {family.members.map((m) => (
                  <li key={m.id} className="flex items-center justify-between py-2">
                    <span className="font-medium text-stone-900">{m.user.display_name}</span>
                    <span className="text-sm capitalize text-stone-500">{m.role}</span>
                  </li>
                ))}
              </ul>
            </Card>
            {canManage && <InviteForm familyId={family.id} />}
          </section>
        </div>

        {/* RIGHT: heritage and the latest happenings */}
        <div className="space-y-8">
          {!isSupporter && (
            <Card className="transition hover:border-emerald-400">
              <a
                href={`/family/${family.id}/legacy`}
                className="flex items-center justify-between"
              >
                <div>
                  <h2 className="text-lg font-semibold text-emerald-900">🌳 Legacy archive</h2>
                  <p className="text-sm text-stone-500">
                    Recipes, stories, and wisdom: your family&apos;s heritage in one place
                  </p>
                </div>
                <span className="text-emerald-700">→</span>
              </a>
            </Card>
          )}

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-semibold text-stone-800">Family moments</h2>
              {feed.length > 0 && (
                <a
                  href={`/family/${family.id}/moments`}
                  className="text-sm font-medium text-emerald-800 hover:text-emerald-900"
                >
                  View all moments →
                </a>
              )}
            </div>
            {feed.length === 0 ? (
              <p className="text-stone-600">
                No moments yet. Share a memory or celebrate a milestone and it will show up
                here for the whole family.
              </p>
            ) : (
              <FamilyFeedList events={latest} />
            )}
          </section>
        </div>
      </div>
    </div>
  );
}

function ChildAvatar({ child }: { child: ChildOut }) {
  if (child.avatar_media_id) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={mediaUrl(child.avatar_media_id)}
        alt={child.first_name}
        className="h-12 w-12 shrink-0 rounded-full object-cover"
      />
    );
  }
  return (
    <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-lg font-semibold text-emerald-800">
      {child.first_name.charAt(0).toUpperCase()}
    </div>
  );
}

function AddChildForm({
  familyId,
  onAdded,
  hasChildren,
}: {
  familyId: string;
  onAdded: () => void;
  hasChildren: boolean;
}) {
  const [name, setName] = useState("");
  const [birthdate, setBirthdate] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const photoRef = useRef<HTMLInputElement>(null);
  // Once a family has children, the form starts collapsed to keep the page calm
  const [open, setOpen] = useState(!hasChildren);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const created = await api.addChild(familyId, name, birthdate, consent);
      const file = photoRef.current?.files?.[0];
      if (file) {
        const mid = await api.uploadMedia(created.id, file);
        await api.setChildAvatar(created.id, mid);
      }
      setName("");
      setBirthdate("");
      setConsent(false);
      if (photoRef.current) photoRef.current.value = "";
      setOpen(false);
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  const title = hasChildren ? "Add another child" : "Add a child";

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="flex w-full items-center justify-center gap-2 rounded-2xl border border-dashed border-stone-300 py-3 text-sm font-medium text-stone-500 hover:border-emerald-400 hover:text-emerald-800"
      >
        + {title}
      </button>
    );
  }

  return (
    <Card>
      <div className="mb-4 flex items-center justify-between">
        <h3 className="font-semibold text-emerald-900">{title}</h3>
        {hasChildren && (
          <button
            onClick={() => setOpen(false)}
            className="text-sm text-stone-400 hover:text-stone-600"
          >
            Close
          </button>
        )}
      </div>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="childname">First name</Label>
            <Input id="childname" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div>
            <Label htmlFor="birthdate">Birthdate</Label>
            <Input
              id="birthdate"
              type="date"
              value={birthdate}
              onChange={(e) => setBirthdate(e.target.value)}
              required
            />
          </div>
        </div>
        <div>
          <Label htmlFor="childphoto">Photo (optional)</Label>
          <input id="childphoto" ref={photoRef} type="file" accept="image/*" className="text-sm" />
        </div>
        <label className="flex items-start gap-3 text-sm text-stone-700">
          <input
            type="checkbox"
            checked={consent}
            onChange={(e) => setConsent(e.target.checked)}
            className="mt-1 h-4 w-4 accent-emerald-700"
            required
          />
          <span>
            As this child&apos;s parent or guardian, I consent to creating their FutureRoots
            profile and to FutureRoots storing the memories our family adds to it.
          </span>
        </label>
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy}>
          {busy ? "Adding…" : "Add child"}
        </Button>
      </form>
    </Card>
  );
}

function InviteForm({ familyId }: { familyId: string }) {
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<FamilyRole>("grandparent");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    setSent(false);
    try {
      await api.createInvite(familyId, email, role);
      setSent(true);
      setEmail("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-4 font-semibold text-emerald-900">Invite a family member</h3>
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="invemail">Their email</Label>
            <Input
              id="invemail"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="invrole">They are a…</Label>
            <select
              id="invrole"
              value={role}
              onChange={(e) => setRole(e.target.value as FamilyRole)}
              className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base"
            >
              <option value="grandparent">Grandparent</option>
              <option value="parent">Parent</option>
              <option value="guardian">Guardian</option>
              <option value="relative">Relative</option>
              <option value="supporter">Supporter (coach, mentor, friend)</option>
            </select>
          </div>
        </div>
        {sent && (
          <p className="rounded-lg bg-emerald-50 px-4 py-2 text-sm text-emerald-900">
            Invitation sent! They&apos;ll get an email with a link to join your family.
          </p>
        )}
        <ErrorNote>{error}</ErrorNote>
        <Button type="submit" disabled={busy}>
          {busy ? "Sending…" : "Send invitation"}
        </Button>
      </form>
    </Card>
  );
}
