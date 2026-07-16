"use client";

import { useEffect, useState } from "react";
import { api, PremiumStatus } from "@/lib/api";

export type SettleState = "waiting" | "settled" | "slow";

export interface PremiumSettleResult {
  state: SettleState;
  /** The premium status as of settling, once state is "settled" (otherwise null).
   * Exposed so success pages can read details (e.g. gift grants) without a
   * second fetch. */
  status: PremiumStatus | null;
}

/** Success-page polling: check the family's premium status every 2 seconds.
 * If it still reads Free after ~6 seconds (a webhook can lag), ask the API to
 * sync from the checkout session once, then keep polling up to ~60 seconds.
 * Entirely request-driven; no client-side state machine beyond this. */
export function usePremiumSettled(
  familyId: string,
  sessionId: string | null
): PremiumSettleResult {
  const [state, setState] = useState<SettleState>("waiting");
  const [status, setStatus] = useState<PremiumStatus | null>(null);

  useEffect(() => {
    if (!familyId) return;
    let cancelled = false;
    let syncTried = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const started = Date.now();

    async function tick() {
      if (cancelled) return;
      try {
        const fetched = await api.getPremiumStatus(familyId);
        if (cancelled) return;
        if (fetched.plan === "premium") {
          setStatus(fetched);
          setState("settled");
          return;
        }
        if (!syncTried && sessionId && Date.now() - started > 6000) {
          syncTried = true;
          const synced = await api.syncPremium(familyId, sessionId);
          if (cancelled) return;
          if (synced.plan === "premium") {
            setStatus(synced);
            setState("settled");
            return;
          }
        }
      } catch {
        // Transient hiccups shouldn't scare anyone on a success page; keep polling.
      }
      if (Date.now() - started > 60000) {
        setState("slow");
        return;
      }
      timer = setTimeout(tick, 2000);
    }

    tick();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [familyId, sessionId]);

  return { state, status };
}
