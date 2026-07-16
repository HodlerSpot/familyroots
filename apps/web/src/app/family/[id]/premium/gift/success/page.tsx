"use client";

import { Suspense, useEffect, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { familyPhrase } from "@/lib/text";
import { Card } from "@/components/ui";
import { usePremiumSettled } from "@/components/premium/usePremiumSettled";

/* All strings verbatim from docs/brand/premium-copy.md §3.3 (final copy deck). */

export default function GiftSuccessPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">Loading…</p>}>
      <GiftSuccessInner />
    </Suspense>
  );
}

function GiftSuccessInner() {
  const { id: familyId } = useParams<{ id: string }>();
  const search = useSearchParams();
  const sessionId = search.get("session_id");
  const { state, status } = usePremiumSettled(familyId, sessionId);
  const [familyName, setFamilyName] = useState("");

  useEffect(() => {
    let cancelled = false;
    api
      .familyDetail(familyId)
      .then((f) => {
        if (!cancelled) setFamilyName(f.name);
      })
      .catch(() => {
        /* the confirmation still reads warmly without the name */
      });
    return () => {
      cancelled = true;
    };
  }, [familyId]);

  const theFamily = familyName ? familyPhrase(familyName, { capitalize: true }) : "The family";

  // The most recently started gift grant is this gift; check whether it
  // carries a note so the confirmation can mention it landed on the feed.
  const latestGrant = status?.grants.length
    ? [...status.grants].sort((a, b) => (a.starts_at < b.starts_at ? 1 : -1))[0]
    : null;
  const hasMessage = Boolean(latestGrant?.message?.trim());

  if (state === "settled") {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <Card className="bg-gradient-to-br from-amber-50 to-emerald-50 text-center">
          <div aria-hidden className="text-5xl">
            🎁
          </div>
          <h1 className="mt-3 text-3xl font-bold text-emerald-900">
            Your gift is on its way to the family feed ♥
          </h1>
          <p className="mt-2 text-stone-600">
            {theFamily} now has a full year of Premium, thanks to you. We&apos;ve let the parents
            know{hasMessage ? ", and your note is on the feed." : "."}
          </p>
          <a
            href={`/family/${familyId}`}
            className="mt-6 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            See the family feed
          </a>
        </Card>
      </div>
    );
  }

  if (state === "slow") {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <Card className="text-center">
          <div aria-hidden className="text-4xl">
            🌱
          </div>
          <h1 className="mt-3 text-2xl font-bold text-emerald-900">Almost there</h1>
          <p className="mt-2 text-stone-600">
            Your payment went through, and your gift is on its way to the family. It sometimes
            takes a minute or two to appear. No need to wait here.
          </p>
          <a
            href={`/family/${familyId}`}
            className="mt-5 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            See the family feed
          </a>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <Card className="text-center">
        <div aria-hidden className="text-4xl motion-safe:animate-pulse">
          ✨
        </div>
        <h1 className="mt-3 text-2xl font-bold text-emerald-900">Finishing up.</h1>
        <p className="mt-2 text-stone-600">This takes a few seconds.</p>
      </Card>
    </div>
  );
}
