"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { goToFundSetup } from "@/components/fund";

/**
 * The warm intro a parent sees before we hand them to the secure,
 * Stripe-hosted setup page. Parents and guardians only.
 */
export default function FundSetupIntroPage() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  const [childName, setChildName] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const vaultPath = `/family/${familyId}/child/${childId}`;

  const load = useCallback(async () => {
    try {
      const [family, me] = await Promise.all([api.familyDetail(familyId), api.me()]);
      const role = family.members.find((m) => m.user.id === me.id)?.role ?? null;
      if (role !== "parent" && role !== "guardian") {
        router.replace(vaultPath);
        return;
      }
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
      setReady(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      } else {
        setError("We couldn't load this page. Please try again from the vault");
        setReady(true);
      }
    }
  }, [familyId, childId, router, vaultPath]);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    load();
  }, [router, load]);

  async function continueToSetup() {
    setBusy(true);
    setError("");
    try {
      await goToFundSetup(childId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  if (!ready) return <p className="text-stone-500">Loading…</p>;

  const poss = childName ? `${childName}'s` : "their";

  return (
    <Card className="mx-auto max-w-lg space-y-6">
      <div className="text-center">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src="/logo-mark.png" alt="" className="mx-auto h-14" />
        <h1 className="mt-2 text-2xl font-bold text-emerald-900">
          Set up {poss} Future Fund
        </h1>
        <p className="mt-1 text-stone-600">
          One-time setup, then anyone in the family can give, grandparents included.
        </p>
      </div>

      <div>
        <h2 className="font-semibold text-stone-800">Have these ready</h2>
        <ul className="mt-2 space-y-3">
          <li className="flex items-start gap-3">
            <span className="text-2xl">🏦</span>
            <span className="text-stone-600">
              The bank account where gifts should go (your routing and account numbers)
            </span>
          </li>
          <li className="flex items-start gap-3">
            <span className="text-2xl">🪪</span>
            <span className="text-stone-600">
              A photo ID. Banks are required to verify who&apos;s opening the account.
            </span>
          </li>
        </ul>
      </div>

      <div>
        <h2 className="font-semibold text-stone-800">How it works</h2>
        <ol className="mt-2 space-y-3">
          {[
            "You'll finish on our secure payments partner, Stripe. It takes about 5 minutes.",
            "Confirm your details and choose the bank account gifts should land in.",
            "Come right back here, and the giving begins.",
          ].map((step, i) => (
            <li key={i} className="flex items-start gap-3">
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-sm font-bold text-emerald-800">
                {i + 1}
              </span>
              <span className="text-stone-600">{step}</span>
            </li>
          ))}
        </ol>
      </div>

      <div className="rounded-xl bg-emerald-50/50 p-4 text-sm text-emerald-900">
        Every gift goes straight to the account you choose, in {poss} corner from
        day one.
      </div>

      <ErrorNote>{error}</ErrorNote>

      <Button onClick={continueToSetup} disabled={busy} className="w-full text-lg">
        {busy ? "One moment…" : "Continue to secure setup →"}
      </Button>

      <button
        onClick={() => router.push(vaultPath)}
        className="w-full text-center text-sm text-stone-500 underline"
      >
        Maybe later
      </button>
    </Card>
  );
}
