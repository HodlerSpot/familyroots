"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, formatMoney, FundAccountStatus, FundOut } from "@/lib/api";
import { Button, Card, ErrorNote } from "@/components/ui";

/** Ask the API for a fresh secure-setup link and follow it. */
export async function goToFundSetup(childId: string): Promise<void> {
  const { url } = await api.startFundSetup(childId);
  window.location.assign(url);
}

function AmberChip({ children }: { children: React.ReactNode }) {
  return (
    <span className="shrink-0 rounded-full bg-amber-100 px-2.5 py-1 text-xs font-semibold text-amber-900">
      {children}
    </span>
  );
}

/**
 * The status-aware "🌳 Future fund" card on the child vault, for family
 * members (parents, guardians, grandparents, relatives). Supporters get
 * their own simpler card on the vault page.
 */
export function FamilyFundCard({
  familyId,
  childId,
  childName,
  fund,
  canManage,
  parentFirstName,
}: {
  familyId: string;
  childId: string;
  childName: string;
  fund: FundOut | null;
  /** true for parents and guardians, who can set up / resume setup */
  canManage: boolean;
  /** first name of the family's first parent, for "Ask {parent}" copy */
  parentFirstName: string | null;
}) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // null = not nudged yet; true = nudge sent; false = they were already told recently
  const [nudged, setNudged] = useState<boolean | null>(null);

  const poss = childName ? `${childName}'s` : "their";

  async function resume() {
    setBusy(true);
    setError("");
    try {
      await goToFundSetup(childId);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
      setBusy(false);
    }
  }

  async function nudge() {
    setBusy(true);
    setError("");
    try {
      // Nudges are quietly deduped server-side; the ✓ always shows.
      const { sent } = await api.nudgeFundSetup(childId);
      setNudged(sent);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
    } finally {
      setBusy(false);
    }
  }

  if (!fund) {
    return (
      <Card className="flex flex-col justify-between bg-emerald-50/50">
        <div>
          <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
          <p className="mt-2 text-3xl font-bold text-emerald-900">…</p>
        </div>
      </Card>
    );
  }

  // --- active: balance + give, as always ---
  if (fund.account_status === "active") {
    return (
      <Card className="flex flex-col justify-between bg-emerald-50/50">
        <div>
          <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
          <p className="mt-2 text-3xl font-bold text-emerald-900">
            {formatMoney(fund.balance_cents, fund.currency)}
          </p>
          <p className="text-sm text-stone-500">
            {fund.gift_count > 0
              ? `${fund.gift_count} gift${fund.gift_count === 1 ? "" : "s"} from the family`
              : "The first gift starts the journey"}
          </p>
        </div>
        <div>
          <Button
            className="mt-4 w-full"
            onClick={() => router.push(`/family/${familyId}/child/${childId}/contribute`)}
          >
            Add to {poss} future
          </Button>
          <p className="mt-2 text-center text-xs text-stone-400">
            Gifts go straight to the account {poss} family chose.
          </p>
        </div>
      </Card>
    );
  }

  // --- none: invite the parent to set it up, or let family nudge them ---
  if (fund.account_status === "none") {
    if (canManage) {
      return (
        <Card className="flex flex-col justify-between bg-emerald-50/50">
          <div>
            <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
            <p className="mt-2 text-sm text-stone-600">
              {`A real account in ${poss} corner. Set it up once and every family gift lands there, growing with ${
                childName || "them"
              } year after year.`}
            </p>
          </div>
          <div>
            <ErrorNote>{error}</ErrorNote>
            <Button
              className="mt-4 w-full"
              onClick={() => router.push(`/family/${familyId}/child/${childId}/fund/setup`)}
            >
              Set up {poss} Future Fund
            </Button>
            <p className="mt-2 text-center text-xs text-stone-400">
              About 5 minutes · secured by Stripe
            </p>
          </div>
        </Card>
      );
    }
    const parent = parentFirstName ?? "a parent";
    return (
      <Card className="flex flex-col justify-between bg-emerald-50/50">
        <div>
          <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
          <p className="mt-2 text-sm text-stone-600">
            {`${poss.charAt(0).toUpperCase() + poss.slice(1)} Future Fund isn't set up yet. Ask ${parent} to set it up. Then the whole family can start giving.`}
          </p>
        </div>
        <div aria-live="polite" className="mt-4">
          <ErrorNote>{error}</ErrorNote>
          {nudged !== null ? (
            <p className="py-3 text-center text-base font-medium text-emerald-800">
              {nudged
                ? `✓ We let ${parentFirstName ?? "them"} know you're ready to give`
                : `✓ ${parentFirstName ?? "They"} already know${parentFirstName ? "s" : ""} you're ready to give`}
            </p>
          ) : (
            <Button variant="soft" className="w-full" onClick={nudge} disabled={busy}>
              💌 Let {parentFirstName ?? "them"} know
            </Button>
          )}
        </div>
      </Card>
    );
  }

  // --- onboarding: partway through setup; gentle amber, never red ---
  if (fund.account_status === "onboarding") {
    const setupBy = fund.setup_by_name?.split(" ")[0] ?? parentFirstName ?? "A parent";
    return (
      <Card className="flex flex-col justify-between border-l-4 border-l-amber-400 bg-amber-50/50">
        <div>
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
            <AmberChip>⏳ Almost there</AmberChip>
          </div>
          <p className="mt-2 text-sm text-stone-600">
            {canManage
              ? `You're partway through setting up ${poss} Future Fund. Pick up right where you left off.`
              : `${setupBy} is finishing the setup. Gifts open the moment it's done.`}
          </p>
        </div>
        {canManage && (
          <div>
            <ErrorNote>{error}</ErrorNote>
            <Button className="mt-4 w-full" onClick={resume} disabled={busy}>
              {busy ? "One moment…" : "Finish setting up"}
            </Button>
            <p className="mt-2 text-center text-xs text-stone-400">
              You&apos;ll finish on our secure payments partner, Stripe, then come right back.
            </p>
          </div>
        )}
      </Card>
    );
  }

  // --- restricted: a quick check is needed; the money never disappears ---
  if (canManage) {
    return (
      <Card className="flex flex-col justify-between border-l-4 border-l-amber-400 bg-amber-50/50">
        <div>
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
            <AmberChip>✋ Needs a quick check</AmberChip>
          </div>
          {fund.balance_cents > 0 && (
            <p className="mt-2 text-3xl font-bold text-emerald-900">
              {formatMoney(fund.balance_cents, fund.currency)}
            </p>
          )}
          <p className="mt-2 text-sm text-stone-600">
            Our payments partner needs one more detail from you before gifts can continue. It
            usually takes a minute.
          </p>
        </div>
        <div>
          <ErrorNote>{error}</ErrorNote>
          <Button className="mt-4 w-full" onClick={resume} disabled={busy}>
            {busy ? "One moment…" : "See what's needed"}
          </Button>
        </div>
      </Card>
    );
  }
  return (
    <Card className="flex flex-col justify-between bg-emerald-50/50">
      <div>
        <h3 className="font-semibold text-emerald-900">🌳 Future fund</h3>
        {fund.balance_cents > 0 && (
          <p className="mt-2 text-3xl font-bold text-emerald-900">
            {formatMoney(fund.balance_cents, fund.currency)}
          </p>
        )}
        <p className="mt-2 text-sm text-stone-600">
          Gifts to {childName || "this little one"} are paused just now. Please try again soon.
        </p>
      </div>
    </Card>
  );
}

/**
 * The "🌳 Give a gift that grows" card supporters see on the child vault.
 * Supporters can't read the fund itself, so this checks the lightweight
 * status endpoint and only offers the contribute button when gifts can land.
 */
export function SupporterFundCard({
  familyId,
  childId,
  childName,
}: {
  familyId: string;
  childId: string;
  childName: string;
}) {
  const router = useRouter();
  const [status, setStatus] = useState<FundAccountStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    api
      .fundStatus(childId)
      .then(({ account_status }) => {
        if (!cancelled) setStatus(account_status);
      })
      .catch(() => {
        // If the check fails, stay on the calm "getting ready" line.
        if (!cancelled) setStatus("none");
      });
    return () => {
      cancelled = true;
    };
  }, [childId]);

  const poss = childName ? `${childName}'s` : "their";

  if (status === "active") {
    return (
      <Card className="flex flex-col items-start gap-3 bg-emerald-50/50 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="font-semibold text-emerald-900">🌳 Give a gift that grows</h3>
          <p className="text-sm text-stone-600">
            Add to {childName || "their"} future and be part of the journey.
          </p>
        </div>
        <Button
          className="w-full sm:w-auto"
          onClick={() => router.push(`/family/${familyId}/child/${childId}/contribute`)}
        >
          Contribute to {poss} future
        </Button>
      </Card>
    );
  }

  return (
    <Card className="bg-emerald-50/50">
      <h3 className="font-semibold text-emerald-900">🌳 Give a gift that grows</h3>
      <p className="mt-1 text-sm text-stone-600">
        {status === null
          ? "…"
          : status === "restricted"
            ? `Gifts to ${childName || "this little one"} are paused just now. Please try again soon.`
            : `${childName ? `${childName}'s` : "Their"} family is getting the Future Fund ready. We'll be glad to see you back soon.`}
      </p>
    </Card>
  );
}
