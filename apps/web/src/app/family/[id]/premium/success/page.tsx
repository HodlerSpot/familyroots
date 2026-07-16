"use client";

import { Suspense } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { Card } from "@/components/ui";
import { usePremiumSettled } from "@/components/premium/usePremiumSettled";

/* All strings verbatim from docs/brand/premium-copy.md §3.3 (final copy deck). */

export default function PremiumSuccessPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">Loading…</p>}>
      <SuccessInner />
    </Suspense>
  );
}

function SuccessInner() {
  const { id: familyId } = useParams<{ id: string }>();
  const search = useSearchParams();
  const sessionId = search.get("session_id");
  const { state } = usePremiumSettled(familyId, sessionId);

  if (state === "settled") {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <Card className="bg-gradient-to-br from-amber-50 to-emerald-50 text-center">
          <div aria-hidden className="text-5xl">
            🎉
          </div>
          <h1 className="mt-3 text-3xl font-bold text-emerald-900">Welcome to Premium</h1>
          <p className="mt-2 text-stone-600">
            Your family&apos;s videos start now. The whole family is in.
          </p>
          <div className="mt-6 flex flex-col gap-2 sm:flex-row sm:justify-center">
            <a
              href={`/family/${familyId}/moments`}
              className="rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
            >
              Share a video
            </a>
            <a
              href={`/family/${familyId}`}
              className="rounded-lg bg-emerald-50 px-5 py-3 text-base font-semibold text-emerald-900 transition-colors hover:bg-emerald-100"
            >
              Start a family call
            </a>
          </div>
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
            Your payment went through, and Premium is on its way to your family. It sometimes
            takes a minute or two to appear. No need to wait here.
          </p>
          <a
            href={`/family/${familyId}`}
            className="mt-5 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            Back to the family
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
