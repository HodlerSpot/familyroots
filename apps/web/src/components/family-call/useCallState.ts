"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, CallState } from "@/lib/api";

/**
 * Polls the family call state every 5s, but only while the browser tab is
 * visible (so a family page left open in a background tab stays quiet). Both
 * the call card and the family page's presence dots read from one instance of
 * this so there is a single source of truth and a single poll.
 */
export function useCallState(familyId: string | undefined, intervalMs = 5000) {
  const [state, setState] = useState<CallState | null>(null);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const refresh = useCallback(async () => {
    if (!familyId) return;
    try {
      const next = await api.callState(familyId);
      setState(next);
    } catch {
      // A transient failure shouldn't blank out the card; keep the last state.
    }
  }, [familyId]);

  useEffect(() => {
    if (!familyId) return;
    let stopped = false;

    const tick = () => {
      if (!stopped && document.visibilityState === "visible") void refresh();
    };

    void refresh();
    timer.current = setInterval(tick, intervalMs);

    const onVisibility = () => {
      if (document.visibilityState === "visible") void refresh();
    };
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stopped = true;
      if (timer.current) clearInterval(timer.current);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [familyId, intervalMs, refresh]);

  return { state, setState, refresh };
}
