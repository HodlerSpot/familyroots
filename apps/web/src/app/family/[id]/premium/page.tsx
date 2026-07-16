"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, getToken, PremiumBillingPlan, PremiumStatus } from "@/lib/api";
import { familyPhrase, formatLongDate } from "@/lib/text";
import { Button, Card, ErrorNote } from "@/components/ui";

/* All strings verbatim from docs/brand/premium-copy.md §1/§3.1 (final copy deck). */

const BENEFITS = [
  {
    lead: "Video memories.",
    text: "Save the recitals, first steps, and belly laughs, in the vault and on the feed.",
  },
  {
    lead: "Family video calls.",
    text: "See everyone's faces, from anywhere, and plan the next call together.",
  },
  {
    lead: "And everything we add next.",
    text: "Premium grows as FutureRoots grows.",
  },
];

export default function PremiumPlanPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">Loading…</p>}>
      <PlanPicker />
    </Suspense>
  );
}

function PlanPicker() {
  const router = useRouter();
  const { id: familyId } = useParams<{ id: string }>();
  const search = useSearchParams();
  const canceled = search.get("canceled") === "1";

  const [familyName, setFamilyName] = useState("");
  const [status, setStatus] = useState<PremiumStatus | null>(null);
  const [plan, setPlan] = useState<PremiumBillingPlan>("annual");
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
      if (err instanceof ApiError && err.status === 401) router.replace("/login");
      else setError(err instanceof ApiError ? err.message : "Couldn't load this page");
    }
  }, [familyId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    load();
  }, [router, load]);

  async function checkout() {
    setBusy(true);
    setError("");
    try {
      const { checkout_url } = await api.createPremiumCheckout(familyId, plan);
      window.location.assign(checkout_url);
    } catch (err) {
      if (err instanceof ApiError && err.code === "already_premium") {
        setError("Your family is already on Premium. There's nothing to buy twice.");
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
      setBusy(false);
    }
  }

  if (!status && error) return <ErrorNote>{error}</ErrorNote>;
  if (!status) return <p className="text-stone-500">Loading…</p>;

  // Billing is a parent's job; everyone else is warmly pointed to the gift.
  if (!status.can_manage) {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <BackLink familyId={familyId} familyName={familyName} />
        <Card>
          <h1 className="text-2xl font-bold text-emerald-900">FutureRoots Premium</h1>
          <p className="mt-2 text-stone-600">
            More room for your family&apos;s story. One membership covers everyone.
          </p>
          <p className="mt-2 text-stone-600">
            A parent looks after the family&apos;s plan. If you&apos;d like, you can give{" "}
            {familyName ? familyPhrase(familyName) : "the family"} a year of Premium as a gift.
          </p>
          <a
            href={`/family/${familyId}/premium/gift`}
            className="mt-4 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            Gift Premium to the family
          </a>
        </Card>
      </div>
    );
  }

  // Already on a recurring plan: nothing to buy here.
  if (status.plan === "premium" && status.subscription) {
    return (
      <div className="mx-auto max-w-xl space-y-6">
        <BackLink familyId={familyId} familyName={familyName} />
        <Card>
          <h1 className="text-2xl font-bold text-emerald-900">FutureRoots Premium</h1>
          <p className="mt-2 text-stone-600">
            Your family is already on Premium. There&apos;s nothing to buy twice.
          </p>
          <a
            href={`/family/${familyId}#plan`}
            className="mt-4 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
          >
            Manage your plan
          </a>
        </Card>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-xl space-y-6">
      <BackLink familyId={familyId} familyName={familyName} />

      <div>
        <h1 className="text-3xl font-bold text-emerald-900">FutureRoots Premium</h1>
        <p className="mt-2 text-stone-600">
          More room for your family&apos;s story. One membership covers everyone.
        </p>
      </div>

      {canceled && (
        <p className="rounded-lg bg-emerald-50 px-4 py-3 text-emerald-900">
          No problem. Everything you already love about FutureRoots stays free, and Premium will
          be right here if you ever want it.
        </p>
      )}

      {status.plan === "premium" && status.premium_until && (
        <p className="rounded-lg bg-amber-50 px-4 py-3 text-sm text-amber-900">
          A gift is covering your family&apos;s Premium until{" "}
          {formatLongDate(status.premium_until)}. A plan you start keeps Premium going when the
          gift ends.
        </p>
      )}

      <Card>
        <ul className="space-y-3">
          {BENEFITS.map((b) => (
            <li key={b.lead} className="text-stone-700">
              <span className="font-semibold text-stone-900">{b.lead}</span> {b.text}
            </li>
          ))}
        </ul>
        <p className="mt-4 text-sm text-stone-400">
          Photos, voice notes, milestones, contributions, goals, capsules, and the archive stay
          free, always.
        </p>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2" role="radiogroup" aria-label="Choose a plan">
        <PlanCard
          selected={plan === "annual"}
          onSelect={() => setPlan("annual")}
          title="Annual"
          price="$99/year"
          badge="Save $20.88 (about 2 months free)"
          note="Renews yearly. Cancel anytime."
        />
        <PlanCard
          selected={plan === "monthly"}
          onSelect={() => setPlan("monthly")}
          title="Monthly"
          price="$9.99/month"
          note="Renews monthly. Cancel anytime."
        />
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
          Premium starts the moment your payment goes through. I agree to it starting right away,
          and I understand this means I give up the 14-day cancellation right that applies in some
          countries. Refund questions? Our support team is happy to help.
        </span>
      </label>

      <Button onClick={checkout} disabled={busy || !immediateAck} className="w-full">
        {busy ? "One moment…" : "Continue to secure checkout"}
      </Button>
      <p className="text-center text-xs text-stone-400">
        Your plan renews automatically until you cancel. Cancel anytime; your family keeps Premium
        until the end of the paid period.
      </p>
    </div>
  );
}

function PlanCard({
  selected,
  onSelect,
  title,
  price,
  badge,
  note,
}: {
  selected: boolean;
  onSelect: () => void;
  title: string;
  price: string;
  badge?: string;
  note: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={`rounded-2xl border-2 bg-white p-5 text-left transition ${
        selected
          ? "border-emerald-600 ring-2 ring-emerald-100"
          : "border-stone-200 hover:border-emerald-300"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-stone-900">{title}</span>
        {selected && (
          <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-900">
            Selected
          </span>
        )}
      </div>
      <p className="mt-2 text-2xl font-bold text-emerald-900">{price}</p>
      {badge && (
        <p className="mt-2 inline-block rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-semibold text-amber-900">
          {badge}
        </p>
      )}
      <p className="mt-2 text-sm text-stone-500">{note}</p>
    </button>
  );
}

function BackLink({ familyId, familyName }: { familyId: string; familyName: string }) {
  return (
    <a href={`/family/${familyId}`} className="text-sm text-stone-500 underline">
      ← {familyName ? `Back to ${familyPhrase(familyName)}` : "Back to the family"}
    </a>
  );
}
