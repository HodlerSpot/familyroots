"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, FeedEventOut, getToken } from "@/lib/api";
import { ErrorNote } from "@/components/ui";
import { FamilyFeedList } from "@/components/feed";

export default function MomentsPage() {
  const router = useRouter();
  const { id } = useParams<{ id: string }>();
  const [feed, setFeed] = useState<FeedEventOut[] | null>(null);
  const [familyName, setFamilyName] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      const [events, family] = await Promise.all([
        api.familyFeed(id),
        api.familyDetail(id),
      ]);
      setFeed(events);
      setFamilyName(family.name);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load family moments");
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
  if (feed === null) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <a href={`/family/${id}`} className="text-sm text-stone-500 underline">
          ← {familyName || "Back to family"}
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">Family moments</h1>
        <p className="text-stone-600">
          Every milestone, memory, and celebration, all in one place for the whole family.
        </p>
      </div>

      <FamilyFeedList events={feed} />
    </div>
  );
}
