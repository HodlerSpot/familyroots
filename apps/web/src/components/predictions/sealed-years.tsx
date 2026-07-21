"use client";

import { useEffect, useState } from "react";
import { api, SealedRoundOut } from "@/lib/api";
import { Card } from "@/components/ui";

/** Family-only strip of locked years waiting for the 18th birthday. No counts,
 * no content, no peek — just the reassurance that they are safely sealed.
 * Self-fetches; renders nothing until at least one year is sealed. */
export function SealedPredictionYears({
  childId,
  childName,
}: {
  childId: string;
  childName: string;
}) {
  const [rounds, setRounds] = useState<SealedRoundOut[] | null>(null);

  useEffect(() => {
    let active = true;
    api
      .listSealedPredictionRounds(childId)
      .then((r) => active && setRounds(r))
      .catch(() => active && setRounds([]));
    return () => {
      active = false;
    };
  }, [childId]);

  if (!rounds || rounds.length === 0) return null;

  const name = childName || "them";
  const opensOn = new Date(rounds[0].opens_on + "T00:00:00").toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });

  return (
    <Card>
      <h3 className="font-semibold text-emerald-900">🔒 Sealed predictions</h3>
      <p className="mt-1 text-sm text-stone-600">
        These years are sealed and stay a surprise for everyone, including you, until {name}
        &apos;s 18th birthday ({opensOn}).
      </p>
      <ul className="mt-3 space-y-2">
        {rounds.map((r) => (
          <li
            key={r.id}
            className="flex items-center justify-between rounded-xl bg-stone-50 px-3 py-2 text-sm"
          >
            <span className="font-medium text-stone-800">{r.year}</span>
            <span className="text-stone-500">Sealed · opens on the 18th birthday</span>
          </li>
        ))}
      </ul>
    </Card>
  );
}
