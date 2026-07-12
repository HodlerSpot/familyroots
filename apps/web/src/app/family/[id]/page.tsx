"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, FamilyDetail, FamilyRole, FeedEventOut, getToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { FamilyFeedList } from "@/components/feed";

export default function FamilyPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [family, setFamily] = useState<FamilyDetail | null>(null);
  const [feed, setFeed] = useState<FeedEventOut[]>([]);
  const [error, setError] = useState("");

  const [myEmail, setMyEmail] = useState("");
  const isParent = family?.members.some(
    (m) => ["parent", "guardian"].includes(m.role) && m.user.email === myEmail
  );

  const load = useCallback(async () => {
    try {
      const [detail, me, events] = await Promise.all([
        api.familyDetail(id),
        api.me(),
        api.familyFeed(id),
      ]);
      setFamily(detail);
      setMyEmail(me.email);
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

  return (
    <div className="space-y-8">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          ← All families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">{family.name}</h1>
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-stone-800">Children</h2>
        {family.children.length === 0 && (
          <p className="text-stone-600">No children added yet.</p>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          {family.children.map((c) => (
            <Card key={c.id} className="transition hover:border-emerald-400">
              <a href={`/family/${family.id}/child/${c.id}`}>
                <h3 className="text-lg font-semibold text-stone-900">{c.first_name}</h3>
                <p className="text-sm text-stone-500">
                  Born {new Date(c.birthdate + "T00:00:00").toLocaleDateString()}
                </p>
                <p className="mt-2 text-sm text-emerald-800">Open {c.first_name}&apos;s vault →</p>
              </a>
            </Card>
          ))}
        </div>
        {isParent && <AddChildForm familyId={family.id} onAdded={load} />}
      </section>

      <Card className="transition hover:border-emerald-400">
        <a href={`/family/${family.id}/legacy`} className="flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold text-emerald-900">🌳 Legacy archive</h2>
            <p className="text-sm text-stone-500">
              Recipes, stories, and wisdom: your family&apos;s heritage in one place
            </p>
          </div>
          <span className="text-emerald-700">→</span>
        </a>
      </Card>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-stone-800">Family moments</h2>
        <FamilyFeedList events={feed} />
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
        {isParent && <InviteForm familyId={family.id} />}
      </section>
    </div>
  );
}

function AddChildForm({ familyId, onAdded }: { familyId: string; onAdded: () => void }) {
  const [name, setName] = useState("");
  const [birthdate, setBirthdate] = useState("");
  const [consent, setConsent] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.addChild(familyId, name, birthdate, consent);
      setName("");
      setBirthdate("");
      setConsent(false);
      onAdded();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <h3 className="mb-4 font-semibold text-emerald-900">Add a child</h3>
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
