"use client";

import { useCallback, useEffect, useState } from "react";
import { api, ApiError, PremiumStatus } from "@/lib/api";
import { formatLongDate } from "@/lib/text";
import { Button, Card, ErrorNote, Modal } from "@/components/ui";
import { PremiumPill } from "./PremiumPill";

/* All strings verbatim from docs/brand/premium-copy.md §3.5 (final copy deck). */

/** The family page's plan block: current plan, renewal, cancel/resume,
 * billing portal (owner only), gift coverage, and the upgrade/gift entries.
 * Anchored at #plan so the families-list badge can deep-link here. */
export function PlanSection({ familyId }: { familyId: string }) {
  const [status, setStatus] = useState<PremiumStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [resumed, setResumed] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await api.getPremiumStatus(familyId));
    } catch {
      // If the plan endpoint isn't reachable, stay quiet rather than alarm
      // anyone; the rest of the family page works exactly as before.
      setUnavailable(true);
    }
  }, [familyId]);

  useEffect(() => {
    load();
  }, [load]);

  if (unavailable || !status) return null;

  const sub = status.subscription;

  async function doCancel() {
    setBusy(true);
    setError("");
    setResumed(false);
    try {
      setStatus(await api.cancelPremium(familyId));
      setConfirmCancel(false);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function doResume() {
    setBusy(true);
    setError("");
    try {
      setStatus(await api.resumePremium(familyId));
      setResumed(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  async function openPortal() {
    setBusy(true);
    setError("");
    try {
      const { portal_url } = await api.createBillingPortal(familyId);
      window.location.assign(portal_url);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  return (
    <section id="plan" className="scroll-mt-6">
      <Card>
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold text-emerald-900">Plan</h2>
          <PremiumPill plan={status.plan} />
        </div>

        {status.plan === "premium" ? (
          <div className="mt-3 space-y-3">
            {sub ? (
              <div className="text-sm text-stone-600">
                {sub.cancel_at_period_end ? (
                  <p>
                    Premium until {formatLongDate(sub.current_period_end)}. Auto-renewal is off.
                  </p>
                ) : (
                  <p>
                    FutureRoots Premium ·{" "}
                    {sub.plan === "annual" ? "Annual, $99/year" : "Monthly, $9.99/month"} · Renews{" "}
                    {formatLongDate(sub.current_period_end)}
                  </p>
                )}
                {sub.status === "past_due" && (
                  <p className="mt-2 rounded-lg bg-amber-50 px-3 py-2 text-amber-900">
                    The last payment didn&apos;t go through, so we&apos;ll retry automatically.
                    Premium stays on for your family in the meantime.
                  </p>
                )}
                {!sub.is_owner && (
                  <p className="mt-1 text-xs text-stone-400">Started by {sub.owner_name}.</p>
                )}
              </div>
            ) : status.premium_until ? (
              <p className="text-sm text-stone-600">
                Premium is on for your family until {formatLongDate(status.premium_until)}.
              </p>
            ) : null}

            {resumed && (
              <p className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                Welcome back. Premium continues without interruption.
              </p>
            )}

            {status.grants.length > 0 && (
              <div>
                <h3 className="text-sm font-semibold text-stone-700">Gifts</h3>
                <ul className="mt-1 space-y-2">
                  {status.grants.map((g, i) => (
                    <li
                      key={`${g.gifter_name}-${g.starts_at}-${i}`}
                      className="rounded-xl bg-amber-50/60 px-3 py-2 text-sm text-stone-700"
                    >
                      A year of Premium from {g.gifter_name}, {formatLongDate(g.starts_at)} to{" "}
                      {formatLongDate(g.ends_at)}
                      {g.message && (
                        <span className="mt-1 block italic text-stone-500">“{g.message}”</span>
                      )}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {status.can_manage && sub && sub.status !== "canceled" && (
              <div className="space-y-2">
                <div className="flex flex-wrap items-center gap-3">
                  {sub.cancel_at_period_end ? (
                    <Button variant="soft" onClick={doResume} disabled={busy}>
                      {busy ? "One moment…" : "Resume Premium"}
                    </Button>
                  ) : (
                    <button
                      type="button"
                      onClick={() => setConfirmCancel(true)}
                      className="text-sm text-stone-500 underline hover:text-stone-700"
                    >
                      Cancel Premium
                    </button>
                  )}
                  {sub.is_owner && (
                    <Button variant="soft" onClick={openPortal} disabled={busy}>
                      Manage billing
                    </Button>
                  )}
                </div>
                {sub.is_owner && (
                  <p className="text-xs text-stone-400">
                    Update your card or view receipts on our secure billing page.
                  </p>
                )}
              </div>
            )}

            {status.can_manage && !sub && (
              <div>
                <a
                  href={`/family/${familyId}/premium`}
                  className="text-sm font-medium text-emerald-800 hover:text-emerald-900"
                >
                  Keep Premium going after the gift →
                </a>
              </div>
            )}

            {status.can_gift && (
              <div>
                <a
                  href={`/family/${familyId}/premium/gift`}
                  className="text-sm font-medium text-emerald-800 hover:text-emerald-900"
                >
                  Give this family a year of Premium →
                </a>
              </div>
            )}
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            <p className="text-sm text-stone-600">
              Everything at the heart of FutureRoots, free forever: photos, voice notes,
              milestones, contributions, goals, capsules, and the archive.
            </p>
            {status.can_manage && (
              <a
                href={`/family/${familyId}/premium`}
                className="inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
              >
                Upgrade to Premium
              </a>
            )}
            {status.can_gift && (
              <div>
                <a
                  href={`/family/${familyId}/premium/gift`}
                  className="text-sm font-medium text-emerald-800 hover:text-emerald-900"
                >
                  Give this family a year of Premium →
                </a>
              </div>
            )}
          </div>
        )}

        {error && (
          <div className="mt-3">
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
      </Card>

      {sub && (
        <Modal
          open={confirmCancel}
          onClose={() => setConfirmCancel(false)}
          title="Cancel Premium?"
        >
          <p className="text-stone-700">
            Premium stays on until {formatLongDate(sub.current_period_end)}. After that your
            family is on the Free plan, and everything you&apos;ve saved stays yours, including
            every video.
          </p>
          <div className="mt-5 flex flex-col gap-2">
            <Button onClick={() => setConfirmCancel(false)}>Keep Premium</Button>
            <Button variant="soft" onClick={doCancel} disabled={busy}>
              {busy ? "One moment…" : "Cancel Premium"}
            </Button>
          </div>
        </Modal>
      )}
    </section>
  );
}
