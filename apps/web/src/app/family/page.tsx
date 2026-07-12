"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, FamilySummary, getToken, setToken } from "@/lib/api";
import { Button, Card, ErrorNote, Input, Label } from "@/components/ui";

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

  function signOut() {
    setToken(null);
    router.replace("/");
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-3xl font-bold text-emerald-900">Your families</h1>
        <span className="space-x-4 text-sm">
          <a href="/account" className="text-stone-500 underline">
            Account
          </a>
          <button onClick={signOut} className="text-stone-500 underline">
            Sign out
          </button>
        </span>
      </div>
      <ErrorNote>{error}</ErrorNote>

      {families === null && !error && <p className="text-stone-500">Loading…</p>}

      {families?.map((f) => (
        <Card key={f.id} className="cursor-pointer transition hover:border-emerald-400">
          <a href={`/family/${f.id}`} className="flex items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <h2 className="text-xl font-semibold text-stone-900">{f.name}</h2>
              <span className="rounded-full bg-emerald-100 px-2.5 py-0.5 text-xs font-semibold capitalize text-emerald-800">
                {f.role}
              </span>
            </div>
            <span className="text-emerald-700">→</span>
          </a>
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
