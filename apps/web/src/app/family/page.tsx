"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, FamilySummary, getToken, setToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";
import { PremiumPill } from "@/components/premium/PremiumPill";

export default function FamilyDashboard() {
  const router = useRouter();
  const [families, setFamilies] = useState<FamilySummary[] | null>(null);
  const [newName, setNewName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setFamilies(await api.myFamilies());
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setToken(null);
        router.replace("/login");
      } else {
        setError("We couldn't load your families. Is the API running?");
      }
    }
  }, [router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  async function createFamily(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const family = await api.createFamily(newName);
      router.push(`/family/${family.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong");
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold text-emerald-900">Your families</h1>
      <ErrorNote>{error}</ErrorNote>

      {families === null && !error && <p className="text-stone-500">Loading…</p>}

      {families?.map((f) => (
        <Card key={f.id} className="transition hover:border-emerald-400">
          <div className="flex items-center justify-between gap-3">
            <a href={`/family/${f.id}`} className="flex min-w-0 flex-1 items-center gap-3">
              <h2 className="truncate text-xl font-semibold text-stone-900">{f.name}</h2>
              <span className="shrink-0 rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold capitalize text-emerald-800">
                {f.role}
              </span>
            </a>
            <div className="flex shrink-0 items-center gap-3">
              {f.plan && (
                // The badge deep-links: a parent on a Free family lands on the
                // plan picker; everyone else lands on the family's Plan section.
                <a
                  href={
                    f.role === "parent" && f.plan === "free"
                      ? `/family/${f.id}/premium`
                      : `/family/${f.id}#plan`
                  }
                >
                  <PremiumPill
                    plan={f.plan}
                    tooltip={
                      f.plan === "premium"
                        ? "This family is on FutureRoots Premium."
                        : f.role === "parent"
                          ? "On the Free plan. See what Premium adds."
                          : "On the Free plan. You can gift Premium anytime."
                    }
                  />
                </a>
              )}
              <a href={`/family/${f.id}`} aria-label={`Open ${f.name}`} className="text-emerald-700">
                →
              </a>
            </div>
          </div>
        </Card>
      ))}

      {families !== null && families.length === 0 && (
        <p className="text-stone-600">
          You haven&apos;t joined a family yet. Start one below, or use an invitation link a
          family member sent you.
        </p>
      )}

      <Card>
        <h2 className="mb-4 text-lg font-semibold text-emerald-900">Start a new family space</h2>
        <form onSubmit={createFamily} className="flex items-end gap-3">
          <div className="flex-1">
            <Label htmlFor="famname">Family name</Label>
            <Input
              id="famname"
              placeholder="e.g. The Johnson Family"
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={busy}>
            Create
          </Button>
        </form>
      </Card>
    </div>
  );
}
