"use client";

import { useEffect, useState } from "react";
import { api, MemoryPromptOut } from "@/lib/api";
import { Button, Card } from "@/components/ui";

// A soft, per-month dismiss lives in localStorage so the card never nags twice
// in the same calendar month. We store the dismissed period ("YYYY-MM"); a new
// month (new period) brings the gentle prompt back on its own.
const DISMISS_KEY = "futureroots_memory_prompt_dismissed";

function readDismissed(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(DISMISS_KEY);
  } catch {
    return null;
  }
}

function writeDismissed(period: string) {
  try {
    localStorage.setItem(DISMISS_KEY, period);
  } catch {
    // Private-mode / storage-full: a non-persisted dismiss is fine.
  }
}

/** Turn a "YYYY-MM" period into a friendly month name, e.g. "July". */
function monthName(period: string): string {
  const parsed = new Date(`${period}-01T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "this month's";
  return parsed.toLocaleString("en-US", { month: "long" });
}

/** A warm, dismissible nudge to add this month's memory for the family's
 * rotating child of the month. It quietly hides itself when there's nothing to
 * ask (the endpoint returns null), when the member has already added a memory
 * this month (`satisfied`), or when they've dismissed it for this period. */
export function MemoryPromptCard({ familyId }: { familyId: string }) {
  const [prompt, setPrompt] = useState<MemoryPromptOut | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .getMemoryPrompt(familyId)
      .then((p) => {
        if (!active) return;
        setPrompt(p);
        if (p && readDismissed() === p.period) setDismissed(true);
      })
      .catch(() => {
        // A gentle extra is never worth an error; just stay hidden.
      });
    return () => {
      active = false;
    };
  }, [familyId]);

  // Nothing to ask, already satisfied this month, or dismissed for this period.
  if (!prompt || prompt.satisfied || dismissed) return null;

  const { child, period } = prompt;

  function dismiss() {
    writeDismissed(period);
    setDismissed(true);
  }

  return (
    <Card className="relative bg-emerald-50/50">
      <button
        type="button"
        onClick={dismiss}
        aria-label="Dismiss this reminder"
        className="absolute right-3 top-3 rounded-full p-1 text-xl leading-none text-stone-400 hover:text-stone-600"
      >
        ×
      </button>
      <div className="pr-6">
        <h3 className="font-semibold text-emerald-900">
          🌱 Add {monthName(period)}&apos;s memory for {child.first_name}
        </h3>
        <p className="mt-2 text-sm text-stone-600">
          A photo, a few words, a little moment: anything you add helps {child.first_name}&apos;s
          story grow. It only takes a minute.
        </p>
      </div>
      <a href={`/family/${familyId}/child/${child.id}`}>
        <Button className="mt-4 w-full">Add a memory for {child.first_name}</Button>
      </a>
    </Card>
  );
}
