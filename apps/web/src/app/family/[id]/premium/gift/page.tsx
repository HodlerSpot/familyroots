"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, getToken, PremiumStatus } from "@/lib/api";
import { familyPhrase } from "@/lib/text";
import { Button, Card, ErrorNote, Label } from "@/components/ui";

/* All strings verbatim from docs/brand/premium-copy.md §3.2 (final copy deck). */

export default function GiftPremiumPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">Loading…</p>}>
      <GiftInner />
    </Suspense>
  );
}

function GiftInner() {
  const router = useRouter();
  const { id: familyId } = useParams<{ id: string }>();
  const search = useSearchParams();
  const canceled = search.get("canceled") === "1";

  const [familyName, setFamilyName] = useState("");
  const [status, setStatus] = useState<PremiumStatus | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [immediateAck, setImmediateAck] = useState(false);

  const load = useCallback(async () => {
    try {
      const [detail, premium] = await Promise.all([
        api.familyDetail(familyId),
        api.getPremiumStatus(familyId),
      ]);
      setFamilyName(detail.name);
      setStatus(premium);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't load this page");
    }
  }, [familyId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  async function checkout(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const { checkout_url } = await api.createGiftCheckout(
        familyId,
        message.trim() || undefined
      );
      window.location.assign(checkout_url);
    } catch (err) {
      if (err instanceof ApiError && err.code === "use_subscribe") {
        setError("As a parent, you can start Premium for the family directly instead.");
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
      setBusy(false);
    }
  }

  if (!status && error) return <ErrorNote>{error}</ErrorNote>;
  if (!status) return <p className="text-stone-500">Loading…</p>;

  const theFamily = familyName ? familyPhrase(familyName) : "the family";

  // Parents manage the plan directly; the gift flow is for everyone else.
  if (status.can_manage) {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <BackLink familyId={familyId} theFamily={theFamily} />
        <Card>
          <h1 className="text-2xl font-bold text-emerald-900">Gifts come from the family</h1>
          <p className="mt-2 text-stone-600">
            As a parent, you can start Premium for the family directly instead.
          </p>
          <a
            href={`/family/${familyId}/premium`}
            className="mt-4 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            See Premium plans
          </a>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <BackLink familyId={familyId} theFamily={theFamily} />

      <div>
        <h1 className="text-3xl font-bold text-emerald-900">
          Give {theFamily} a year of Premium
        </h1>
        <p className="mt-2 text-stone-600">
          $99, one time. Twelve months of video memories and family video calls, from you.
        </p>
      </div>

      {canceled && (
        <p className="rounded-lg bg-emerald-50 px-4 py-3 text-emerald-900">
          No worries at all. The family is right here whenever you&apos;re ready, and so is the
          gift.
        </p>
      )}

      {status.plan === "premium" && (
        <p className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
          This family already has Premium. Your gift will extend it by a full year, starting when
          their current coverage ends.
        </p>
      )}

      <Card>
        <p className="text-sm text-stone-600">
          Your gift is fully prepaid. It never charges the parents, it doesn&apos;t renew, and
          there&apos;s nothing for them to set up. The whole family gets Premium the moment your
          gift goes through, and they&apos;ll see it came from you.
        </p>
        <form onSubmit={checkout} className="mt-4 space-y-4">
          <div>
            <Label htmlFor="giftmsg">Add a note the family will see</Label>
            <textarea
              id="giftmsg"
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              maxLength={500}
              rows={3}
              placeholder="For all the recital videos to come ♥"
              className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none"
            />
            <p className="mt-1 text-xs text-stone-400">
              Up to 500 characters. It appears on the family feed and in the parents&apos; email.
            </p>
          </div>
          <ErrorNote>{error}</ErrorNote>

          <label htmlFor="immediate-ack" className="flex items-start gap-2 text-xs text-stone-500">
            <input
              id="immediate-ack"
              type="checkbox"
              checked={immediateAck}
              onChange={(e) => setImmediateAck(e.target.checked)}
              required
              className="mt-0.5 h-4 w-4 shrink-0 rounded border-stone-300 text-emerald-700 focus:ring-emerald-600"
            />
            <span>
              The gift year starts right away, the moment your payment goes through. I agree to it
              starting immediately, and I understand this means I give up the 14-day cancellation
              right that applies in some countries. Refund questions? Our support team is happy to
              help.
            </span>
          </label>

          <Button type="submit" disabled={busy || !immediateAck} className="w-full">
            {busy ? "One moment…" : "Continue to payment"}
          </Button>
          <p className="text-center text-xs text-stone-400">
            One-time payment of $99. Nothing renews, and no one is charged later.
          </p>
        </form>
      </Card>
    </div>
  );
}

function BackLink({ familyId, theFamily }: { familyId: string; theFamily: string }) {
  return (
    <a href={`/family/${familyId}`} className="text-sm text-stone-500 underline">
      ← Back to {theFamily}
    </a>
  );
}
