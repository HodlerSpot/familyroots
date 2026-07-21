"use client";

import { CloudWordOut } from "@/lib/api";

// The three brand text colors, cycled by index (the same palette the sealed
// keepsake image uses). Client-side only: the open round re-renders instantly
// on every add or edit, so the cloud is always current.
const CLOUD_COLORS = ["text-emerald-800", "text-amber-700", "text-stone-600"];

/** The live word cloud for the OPEN round, rendered from the API's
 * `{word, weight}` list. Words are sized by weight; a visually hidden count
 * keeps it readable for screen readers. No external libraries. */
export function WordCloud({ words }: { words: CloudWordOut[] }) {
  if (words.length === 0) {
    return (
      <p className="text-sm text-stone-500">
        No words yet. Add the first prediction and watch it appear here.
      </p>
    );
  }

  const weights = words.map((w) => w.weight);
  const min = Math.min(...weights);
  const max = Math.max(...weights);
  const sizeFor = (weight: number): number => {
    if (max === min) return 24;
    return Math.round(16 + 26 * ((weight - min) / (max - min)));
  };

  return (
    <ul
      className="flex flex-wrap items-baseline gap-x-4 gap-y-1"
      aria-label="The words the family has predicted, larger where more people said the same thing"
    >
      {words.map((w, i) => (
        <li
          key={w.word}
          className={`font-semibold leading-tight ${CLOUD_COLORS[i % CLOUD_COLORS.length]}`}
          style={{ fontSize: `${sizeFor(w.weight)}px` }}
        >
          {w.word}
          <span className="sr-only">
            {" "}
            (said {w.weight} {w.weight === 1 ? "time" : "times"})
          </span>
        </li>
      ))}
    </ul>
  );
}
