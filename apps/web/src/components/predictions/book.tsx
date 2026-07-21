"use client";

import { mediaUrl, PredictionBookOut } from "@/lib/api";
import { Card, ZoomableImage } from "@/components/ui";

/** The released Book of Predictions: one chapter per sealed year, each showing
 * the sealed keepsake image (a server-rendered PNG served like every other
 * vault/feed image, via `mediaUrl` + the short-lived media token) above the
 * full attributed list. Chronological, oldest first. */
export function PredictionBookView({ book }: { book: PredictionBookOut }) {
  const name = book.child_first_name || "them";

  if (book.chapters.length === 0) {
    return (
      <Card>
        <p className="text-stone-600">
          The book opens on the 18th birthday. When it does, every sealed year of the family&apos;s
          predictions appears here together.
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-8">
      {book.chapters.map((ch) => (
        <Card key={ch.round_id} className="space-y-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="text-xl font-semibold text-emerald-900">{ch.year}</h2>
            <span className="text-sm text-stone-500">
              The year {name} turned {ch.age}
            </span>
          </div>

          {ch.cloud_media_id && (
            <ZoomableImage
              src={mediaUrl(ch.cloud_media_id)}
              alt={`The family's predictions for ${name} in ${ch.year}`}
              className="w-full rounded-xl border border-stone-100 object-contain"
            />
          )}

          <ul className="space-y-2">
            {ch.predictions.map((p, i) => (
              <li key={`${ch.round_id}-${i}`} className="rounded-xl bg-stone-50 px-3 py-2">
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm font-semibold text-stone-900">{p.author_name}</span>
                  <span className="shrink-0 text-xs text-stone-400">
                    {new Date(p.created_at).toLocaleDateString()}
                  </span>
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-stone-700">{p.body}</p>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}
