"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  api,
  ApiError,
  BadgeOut,
  CapsuleOut,
  formatMoney,
  FundOut,
  getToken,
  GoalOut,
  mediaUrl,
  VaultItemOut,
} from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { CapsulesSection } from "@/components/capsules";

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
  const [fund, setFund] = useState<FundOut | null>(null);
  const [goals, setGoals] = useState<GoalOut[]>([]);
  const [badges, setBadges] = useState<BadgeOut[]>([]);
  const [capsules, setCapsules] = useState<CapsuleOut[]>([]);
  const [isParent, setIsParent] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [vault, family, me, fundData, goalsData, badgesData, capsulesData] =
        await Promise.all([
          api.listVault(childId),
          api.familyDetail(familyId),
          api.me(),
          api.childFund(childId),
          api.listGoals(childId),
          api.listBadges(childId),
          api.listCapsules(childId),
        ]);
      setItems(vault);
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
      setFund(fundData);
      setGoals(goalsData);
      setBadges(badgesData);
      setCapsules(capsulesData);
      setIsParent(
        family.members.some(
          (m) => ["parent", "guardian"].includes(m.role) && m.user.email === me.email
        )
      );
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

      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="flex flex-col justify-between bg-emerald-50/50">
          <div>
            <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
            <p className="mt-2 text-3xl font-bold text-emerald-900">
              {fund ? formatMoney(fund.balance_cents, fund.currency) : "…"}
            </p>
            <p className="text-sm text-stone-500">
              {fund && fund.entries.length > 0
                ? `${fund.entries.length} gift${fund.entries.length === 1 ? "" : "s"} from the family`
                : "The first gift starts the journey"}
            </p>
          </div>
          <Button
            className="mt-4 w-full"
            onClick={() => router.push(`/family/${familyId}/child/${childId}/contribute`)}
          >
            Add to {childName ? `${childName}'s` : "their"} future
          </Button>
        </Card>
        <Card>
          <h3 className="font-semibold text-emerald-900">🏅 Badges</h3>
          {badges.length === 0 ? (
            <p className="mt-2 text-sm text-stone-500">
              Badges appear when {childName || "they"} complete{childName ? "s" : ""} goals.
            </p>
          ) : (
            <div className="mt-3 flex flex-wrap gap-2">
              {badges.map((b) => (
                <span
                  key={b.id}
                  className="rounded-full bg-amber-50 px-3 py-1 text-sm text-amber-900"
                  title={new Date(b.awarded_at).toLocaleDateString()}
                >
                  {b.icon} {b.label}
                </span>
              ))}
            </div>
          )}
        </Card>
      </div>

      <GoalsSection
        childId={childId}
        childName={childName}
        goals={goals}
        isParent={isParent}
        onChanged={load}
      />

      <CapsulesSection
        childId={childId}
        childName={childName}
        capsules={capsules}
        isParent={isParent}
        onChanged={load}
      />

      <div className="grid gap-4 md:grid-cols-2">
        <MilestoneForm childId={childId} onPosted={load} childName={childName} />
        <MemoryForm childId={childId} onAdded={load} childName={childName} />
      </div>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold text-stone-800">Memories & milestones</h2>
        {items.length === 0 && (
          <p className="text-stone-600">
            The vault is empty. Share the first memory above.
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

const REWARD_LABELS: Record<string, string> = {
  badge: "🏅 Badge",
  cash: "💵 Cash reward",
  fund_contribution: "🌳 Future fund gift",
  privilege: "⭐ Family privilege",
};

function GoalsSection({
  childId,
  childName,
  goals,
  isParent,
  onChanged,
}: {
  childId: string;
  childName: string;
  goals: GoalOut[];
  isParent: boolean;
  onChanged: () => void;
}) {
  const [showForm, setShowForm] = useState(false);
  const [title, setTitle] = useState("");
  const [rewardType, setRewardType] = useState<"badge" | "cash" | "fund_contribution" | "privilege">("badge");
  const [rewardAmount, setRewardAmount] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function createGoal(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.createGoal(childId, {
        title,
        reward_type: rewardType,
        reward_amount_cents:
          rewardType === "cash" || rewardType === "fund_contribution"
            ? Math.round(parseFloat(rewardAmount || "0") * 100)
            : undefined,
      });
      setTitle("");
      setRewardAmount("");
      setShowForm(false);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  }

  async function complete(goalId: string) {
    setError("");
    try {
      await api.completeGoal(goalId);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
    }
  }

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold text-stone-800">Goals</h2>
        {isParent && (
          <Button variant="soft" onClick={() => setShowForm((v) => !v)}>
            {showForm ? "Close" : "+ New goal"}
          </Button>
        )}
      </div>
      <ErrorNote>{error}</ErrorNote>

      {showForm && (
        <Card>
          <form onSubmit={createGoal} className="space-y-3">
            <div>
              <Label htmlFor="gtitle">Goal</Label>
              <Input
                id="gtitle"
                placeholder="e.g. Read 10 books"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label htmlFor="greward">Reward</Label>
                <select
                  id="greward"
                  value={rewardType}
                  onChange={(e) => setRewardType(e.target.value as typeof rewardType)}
                  className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base"
                >
                  <option value="badge">🏅 Badge</option>
                  <option value="cash">💵 Cash</option>
                  <option value="fund_contribution">🌳 Future fund gift</option>
                  <option value="privilege">⭐ Family privilege</option>
                </select>
              </div>
              {(rewardType === "cash" || rewardType === "fund_contribution") && (
                <div>
                  <Label htmlFor="gamount">Amount ($)</Label>
                  <Input
                    id="gamount"
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={rewardAmount}
                    onChange={(e) => setRewardAmount(e.target.value)}
                    required
                  />
                </div>
              )}
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create goal"}
            </Button>
          </form>
        </Card>
      )}

      {goals.length === 0 && !showForm && (
        <p className="text-stone-600">
          {isParent
            ? `Set a goal for ${childName || "your child"} (reading, chores, practice) and celebrate when they get there.`
            : "No goals yet."}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        {goals.map((g) => (
          <Card key={g.id} className={g.status === "completed" ? "opacity-70" : ""}>
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="font-semibold text-stone-900">
                  {g.status === "completed" ? "✅ " : ""}
                  {g.title}
                </h3>
                <p className="mt-1 text-sm text-stone-500">
                  {REWARD_LABELS[g.reward_type]}
                  {g.reward_amount_cents ? ` · ${formatMoney(g.reward_amount_cents, g.currency)}` : ""}
                </p>
              </div>
              {isParent && g.status === "active" && (
                <Button variant="soft" onClick={() => complete(g.id)}>
                  Done!
                </Button>
              )}
            </div>
          </Card>
        ))}
      </div>
    </section>
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
