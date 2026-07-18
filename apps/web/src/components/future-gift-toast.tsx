"use client";

import { useEffect, useRef, useState } from "react";

const DISPLAY_MS = 3500;

/**
 * A quick, one-at-a-time banner confirming how much a member just added to a
 * child's Future Gift (a memory, a milestone, or a time capsule). Page-local:
 * driven entirely by the `message` the caller passes in, with no app-wide
 * provider or layout change. Auto-dismisses after a few seconds, or on tap;
 * a new message replaces whatever is currently showing.
 *
 * Slides and fades in on mount; under `prefers-reduced-motion` it simply
 * appears, no transform or fade.
 */
export function FutureGiftToast({
  message,
  onDismiss,
}: {
  message: string | null;
  onDismiss: () => void;
}) {
  const [shown, setShown] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    if (!message) {
      setShown(false);
      return;
    }
    setShown(false);
    const raf = requestAnimationFrame(() => setShown(true));
    timerRef.current = setTimeout(onDismiss, DISPLAY_MS);
    return () => {
      cancelAnimationFrame(raf);
      if (timerRef.current) clearTimeout(timerRef.current);
    };
    // Re-run whenever a new message arrives so a replacement toast restarts
    // its own dismiss timer; onDismiss is stable enough in practice.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [message]);

  if (!message) return null;

  return (
    <div className="pointer-events-none fixed inset-x-0 bottom-6 z-50 flex justify-center px-4">
      <p
        role="status"
        aria-live="polite"
        onClick={onDismiss}
        className={`pointer-events-auto max-w-sm cursor-pointer rounded-full bg-gradient-to-r from-amber-100 to-amber-50 px-5 py-3 text-center text-sm font-medium text-amber-900 shadow-lg ring-1 ring-amber-200 transition-all duration-300 ease-out motion-reduce:transition-none ${
          shown ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0"
        }`}
      >
        {message}
      </p>
    </div>
  );
}
