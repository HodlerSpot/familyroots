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
  MemberOut,
} from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label, Modal } from "@/components/ui";
import { FamilyFeedList } from "@/components/feed";
import { FamilyCallCard } from "@/components/family-call/FamilyCallCard";
import { useCallState } from "@/components/family-call/useCallState";
import { PremiumPill } from "@/components/premium/PremiumPill";
import { PlanSection } from "@/components/premium/PlanSection";
import { FutureGifts } from "@/components/future-gifts";
import { MemoryPromptCard } from "@/components/memory-prompt-card";

export default function FamilyPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [family, setFamily] = useState<FamilyDetail | null>(null);
  const [feed, setFeed] = useState<FeedEventOut[]>([]);
  const [myRole, setMyRole] = useState<FamilyRole | null>(null);
  const [meId, setMeId] = useState<string | null>(null);
  const [error, setError] = useState("");

  // Departure flows: a quiet way out for yourself, and (parents only) a
  // gentle way to remove someone. Nothing anyone shared is ever deleted.
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [leaveBusy, setLeaveBusy] = useState(false);
  const [leaveError, setLeaveError] = useState("");
  const [ownsPremium, setOwnsPremium] = useState(false);
  const [removeTarget, setRemoveTarget] = useState<MemberOut | null>(null);
  const [removeBusy, setRemoveBusy] = useState(false);
  const [removeError, setRemoveError] = useState("");

  // Supporters (coaches, mentors, friends) get a warm, view-only experience:
  // no legacy archive, no family administration. Everyone else sees the archive
  // and moments, but only parents/guardians manage the family (add children, invite).
  const isSupporter = myRole === "supporter";
  const canManage = myRole === "parent" || myRole === "guardian";

  // One shared source of call truth: the card polls this, and the member/child
  // presence dots below read from the very same state.
  const { state: callState, refresh: refreshCall } = useCallState(family ? id : undefined);
  const onCallUserIds = new Set((callState?.participants ?? []).map((p) => p.user_id));
  const childrenOnCall = new Set((callState?.children_present ?? []).map((c) => c.child_id));

  const load = useCallback(async () => {
    try {
      const [detail, me, events] = await Promise.all([
        api.familyDetail(id),
        api.me(),
        api.familyFeed(id),
      ]);
      setFamily(detail);
      setMeId(me.id);
      setMyRole(detail.members.find((m) => m.user.id === me.id)?.role ?? null);
      setFeed(events);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this family");
    }
  }, [id, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  async function openLeave() {
    setLeaveError("");
    setOwnsPremium(false);
    setConfirmLeave(true);
    // Only a parent can own the family's Premium subscription; if the person
    // leaving started it, the dialog must say so before they decide.
    if (myRole === "parent") {
      try {
        const s = await api.getPremiumStatus(id);
        setOwnsPremium(
          Boolean(s.subscription && s.subscription.is_owner && s.subscription.status !== "canceled")
        );
      } catch {
        // If the plan can't be checked, keep the dialog calm and generic.
      }
    }
  }

  async function doLeave() {
    setLeaveBusy(true);
    setLeaveError("");
    try {
      await api.leaveFamily(id);
      router.replace("/family");
    } catch (err) {
      setLeaveError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
      setLeaveBusy(false);
    }
  }

  async function doRemove() {
    if (!removeTarget) return;
    setRemoveBusy(true);
    setRemoveError("");
    try {
      await api.removeFamilyMember(id, removeTarget.user.id);
      setRemoveTarget(null);
      await load();
    } catch (err) {
      setRemoveError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    } finally {
      setRemoveBusy(false);
    }
  }

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!family) return <p className="text-stone-500">Loading…</p>;

  const latest = feed.slice(0, 3);

  return (
    <div className="space-y-8">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          ← All families
        </a>
        <div className="mt-2 flex items-center gap-3">
          <h1 className="text-3xl font-bold text-emerald-900">{family.name}</h1>
          {family.plan && <PremiumPill plan={family.plan} />}
        </div>
      </div>

      {/* A gentle monthly nudge to add a memory for the child of the month. It
          self-hides for supporters, childless families, and anyone who has
          already added a memory this month, so it's safe to mount for everyone. */}
      <MemoryPromptCard familyId={family.id} />

      {!isSupporter && (
        <FamilyCallCard
          familyId={family.id}
          familyName={family.name}
          children={family.children}
          state={callState}
          onRefresh={refreshCall}
          capabilities={family.capabilities}
          role={myRole}
        />
      )}

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
                      <FutureGifts
                        seconds={c.future_gifts_seconds}
                        childName={c.first_name}
                        variant="compact"
                      />
                      {childrenOnCall.has(c.id) && (
                        <span className="mt-1 inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-medium text-emerald-900">
                          <span
                            aria-hidden
                            className="h-1.5 w-1.5 rounded-full bg-emerald-500 motion-safe:animate-pulse"
                          />
                          On the family call now
                        </span>
                      )}
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
                {family.members.map((m) => {
                  const onCall = onCallUserIds.has(m.user.id);
                  return (
                    <li key={m.id} className="flex items-center justify-between py-2">
                      <span className="flex items-center gap-2 font-medium text-stone-900">
                        {onCall && (
                          <span className="flex items-center">
                            <span
                              aria-hidden
                              className="h-2.5 w-2.5 rounded-full bg-emerald-500 motion-safe:animate-pulse"
                            />
                            <span className="sr-only">on the family call now</span>
                          </span>
                        )}
                        {m.user.display_name}
                      </span>
                      <span className="flex items-center gap-3">
                        <span className="text-sm capitalize text-stone-500">{m.role}</span>
                        {myRole === "parent" && m.user.id !== meId && (
                          <button
                            type="button"
                            onClick={() => {
                              setRemoveError("");
                              setRemoveTarget(m);
                            }}
                            className="text-xs text-stone-400 underline hover:text-stone-600"
                          >
                            Remove
                          </button>
                        )}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </Card>
            {canManage && <InviteForm familyId={family.id} />}
            <div className="pt-1">
              <button
                type="button"
                onClick={openLeave}
                className="text-xs text-stone-400 underline hover:text-stone-600"
              >
                Leave this family
              </button>
            </div>
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

          <PlanSection familyId={family.id} />
        </div>
      </div>

      <Modal open={confirmLeave} onClose={() => setConfirmLeave(false)} title="Leave this family?">
        <p className="text-stone-700">
          You can step away whenever you need to. Everything you&apos;ve shared stays with the
          family, and a parent can invite you back any time.
        </p>
        {ownsPremium && (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
            You started this family&apos;s Premium membership, so it won&apos;t renew after you
            leave. Premium stays on for everyone until the end of the current billing period.
          </p>
        )}
        {leaveError && (
          <div className="mt-3">
            <ErrorNote>{leaveError}</ErrorNote>
          </div>
        )}
        <div className="mt-5 flex flex-col gap-2">
          <Button onClick={() => setConfirmLeave(false)}>Stay</Button>
          <Button variant="soft" onClick={doLeave} disabled={leaveBusy}>
            {leaveBusy ? "One moment…" : "Leave family"}
          </Button>
        </div>
      </Modal>

      <Modal
        open={removeTarget !== null}
        onClose={() => setRemoveTarget(null)}
        title={`Remove ${removeTarget?.user.display_name ?? "this member"}?`}
      >
        <p className="text-stone-700">
          {removeTarget?.user.display_name} won&apos;t see this family anymore. Nothing
          they&apos;ve shared is deleted, and you can invite them back whenever you like.
        </p>
        {removeError && (
          <div className="mt-3">
            <ErrorNote>{removeError}</ErrorNote>
          </div>
        )}
        <div className="mt-5 flex flex-col gap-2">
          <Button onClick={() => setRemoveTarget(null)}>Keep them</Button>
          <Button variant="soft" onClick={doRemove} disabled={removeBusy}>
            {removeBusy ? "One moment…" : "Remove"}
          </Button>
        </div>
      </Modal>
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
              <option value="aunt">Aunt</option>
              <option value="uncle">Uncle</option>
              <option value="cousin">Cousin</option>
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
