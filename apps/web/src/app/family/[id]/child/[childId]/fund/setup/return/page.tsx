"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { api, ApiError, FundAccountStatus, getToken } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";
import { goToFundSetup } from "@/components/fund";

/** Where the parent lands after finishing (or leaving) the secure setup page. */
export default function FundSetupReturnPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">One moment…</p>}>
      <ReturnInner />
    </Suspense>
  );
}

interface SetupStatus {
  account_status: FundAccountStatus;
  payouts_enabled: boolean;
  requirements_due: boolean;
}

function ReturnInner() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  // Local dev's pretend setup page returns with ?simulated=1; status is
  // authoritative either way, we just tag the wrapper for test tooling.
  const simulated = useSearchParams().get("simulated") === "1";
  const [status, setStatus] = useState<SetupStatus | null>(null);
  const [childName, setChildName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const vaultPath = `/family/${familyId}/child/${childId}`;

  const load = useCallback(async () => {
    try {
      const [setup, family] = await Promise.all([
        api.fundSetupStatus(childId),
        api.familyDetail(familyId),
      ]);
      setChildName(family.children.find((c) => c.id === childId)?.first_name ?? "");
      setStatus(setup);
    } catch (err) {
      setError("We couldn't check on the fund just now. Please try again from the vault");
    }
  }, [childId, familyId, router]);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    load();
  }, [router, load]);

  async function finishSetup() {
    setBusy(true);
    setError("");
    try {
      await goToFundSetup(childId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  if (error && !status) {
    return (
      <Card className="mx-auto max-w-lg space-y-4 text-center">
        <ErrorNote>{error}</ErrorNote>
        <Button variant="soft" className="w-full" onClick={() => router.push(vaultPath)}>
          Back to {childName ? `${childName}'s` : "the"} vault
        </Button>
      </Card>
    );
  }

  if (!status) return <p className="text-stone-500">One moment…</p>;

  const poss = childName ? `${childName}'s` : "their";
  const backLabel = `Back to ${poss} vault`;

  // Ready: gifts can flow.
  if (status.account_status === "active") {
    return (
      <Card data-simulated={simulated || undefined} className="mx-auto max-w-lg space-y-4 text-center">
        <div className="text-5xl">🎉</div>
        <h1 className="text-2xl font-bold text-emerald-900">{poss.charAt(0).toUpperCase() + poss.slice(1)} Future Fund is ready</h1>
        <p className="text-stone-600">
          Gifts from the whole family now go straight to the account you chose.
        </p>
        <Button
          className="w-full text-lg"
          onClick={() => router.push(`${vaultPath}/contribute`)}
        >
          Add the first gift
        </Button>
        <button
          onClick={() => router.push(vaultPath)}
          className="w-full text-center text-sm text-stone-500 underline"
        >
          {backLabel}
        </button>
      </Card>
    );
  }

  // Something still to do: an extra detail is needed (or setup never finished).
  if (status.requirements_due || status.account_status !== "onboarding") {
    return (
      <Card data-simulated={simulated || undefined} className="mx-auto max-w-lg space-y-4 text-center">
        <div className="text-5xl">✋</div>
        <h1 className="text-2xl font-bold text-emerald-900">One more thing needed</h1>
        <p className="text-stone-600">
          Our payments partner needs an extra detail before {poss} fund can open. It usually
          takes a minute.
        </p>
        <ErrorNote>{error}</ErrorNote>
        <Button className="w-full text-lg" onClick={finishSetup} disabled={busy}>
          {busy ? "One moment…" : "Finish setting up"}
        </Button>
        <button
          onClick={() => router.push(vaultPath)}
          className="w-full text-center text-sm text-stone-500 underline"
        >
          {backLabel}
        </button>
      </Card>
    );
  }

  // All submitted, just waiting on a final review.
  return (
    <Card data-simulated={simulated || undefined} className="mx-auto max-w-lg space-y-4 text-center">
      <div className="text-5xl">🌱</div>
      <h1 className="text-2xl font-bold text-emerald-900">Almost there, just growing</h1>
      <p className="text-stone-600">
        Our payments partner is doing a final review. This usually takes less than a day, and
        we&apos;ll email you the moment {poss} fund is ready.
      </p>
      <Button className="w-full text-lg" onClick={() => router.push(vaultPath)}>
        {backLabel}
      </Button>
    </Card>
  );
}
