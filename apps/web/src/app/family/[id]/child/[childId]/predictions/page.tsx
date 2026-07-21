"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { api, ApiError, getToken, PredictionBookOut } from "@/lib/api";
import { ErrorNote } from "@/components/ui";
import { PredictionBookView } from "@/components/predictions/book";

export default function PredictionBookPage() {
  const router = useRouter();
  const { id: familyId, childId } = useParams<{ id: string; childId: string }>();
  const [book, setBook] = useState<PredictionBookOut | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setBook(await api.getPredictionBook(childId));
    } catch (err) {
      // The book is family-only; supporters get a 403 they should never reach
      // (no link is ever shown to them), handled warmly just in case.
      if (err instanceof ApiError && err.status === 403) {
        setError("The Book of Predictions is shared with family members only.");
      } else {
        setError(err instanceof ApiError ? err.message : "We couldn't open the book just now.");
      }
    }
  }, [childId]);

  useEffect(() => {
    if (!getToken()) {
      router.replace(`/login?next=${encodeURIComponent(location.pathname)}`);
      return;
    }
    load();
  }, [router, load]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (!book) return <p className="text-stone-500">Loading…</p>;

  const name = book.child_first_name || "them";

  return (
    <div className="space-y-6">
      <div>
        <a
          href={`/family/${familyId}/child/${childId}`}
          className="text-sm text-stone-500 underline"
        >
          ← Back to the vault
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">
          {name}&apos;s Book of Predictions
        </h1>
        <p className="text-stone-600">
          Years of the family imagining who {name} would become.
        </p>
      </div>
      <PredictionBookView book={book} />
    </div>
  );
}
