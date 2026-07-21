"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError, formatMoney, getToken, MyContribution } from "@/lib/api";
import { Card, ErrorNote } from "@/components/ui";

const CHIP: Record<MyContribution["status"], string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

const STATUS_LABEL: Record<MyContribution["status"], string> = {
  succeeded: "Given",
  pending: "Processing",
  failed: "Didn't go through",
  refunded: "Refunded",
};

export default function ContributionsPage() {
  const router = useRouter();
  const [items, setItems] = useState<MyContribution[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!getToken()) {
      router.replace("/login?next=/contributions");
      return;
    }
    api
      .myContributions()
      .then(setItems)
      .catch((err) => {
        setError(err instanceof ApiError ? err.message : "Couldn't load your contributions");
      });
  }, [router]);

  if (error) return <ErrorNote>{error}</ErrorNote>;
  if (items === null) return <p className="text-stone-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div>
        <a href="/family" className="text-sm text-stone-500 underline">
          Back to your families
        </a>
        <h1 className="mt-2 text-3xl font-bold text-emerald-900">My contributions</h1>
        <p className="mt-2 text-stone-600">
          Every gift you&apos;ve given to a little one&apos;s future, all in one place.
        </p>
      </div>

      {items.length === 0 ? (
        <Card className="text-center">
          <div className="text-4xl">🌱</div>
          <p className="mx-auto mt-3 max-w-md text-stone-600">
            You haven&apos;t made any contributions yet. When you help grow a child&apos;s future
            fund, it will show up here.
          </p>
        </Card>
      ) : (
        <Card className="overflow-hidden p-0">
          <ul className="divide-y divide-stone-100">
            {items.map((c) => (
              <li key={c.id} className="flex flex-wrap items-start gap-4 px-4 py-4 sm:px-6">
                <div className="min-w-0 flex-1">
                  <p className="font-semibold text-stone-900">
                    {c.child_name}
                    <span className="font-normal text-stone-500"> · {c.family_name}</span>
                  </p>
                  <p className="mt-0.5 text-xs text-stone-400">
                    {new Date(c.created_at).toLocaleDateString(undefined, {
                      year: "numeric",
                      month: "long",
                      day: "numeric",
                    })}
                  </p>
                  {c.message && (
                    <p className="mt-2 whitespace-pre-wrap text-sm text-stone-700">
                      &ldquo;{c.message}&rdquo;
                    </p>
                  )}
                </div>
                <div className="text-right">
                  <p className="text-lg font-bold tabular-nums text-emerald-800">
                    {formatMoney(c.amount_cents, c.currency)}
                  </p>
                  <span
                    className={`mt-1 inline-block rounded-full px-2 py-0.5 text-[11px] font-semibold ${CHIP[c.status]}`}
                  >
                    {STATUS_LABEL[c.status]}
                  </span>
                  {c.fee_cents > 0 && (
                    <p className="mt-1 text-[11px] text-stone-500">
                      {formatMoney(c.amount_cents - c.fee_cents, c.currency)} delivered to{" "}
                      {c.child_name}&apos;s fund
                    </p>
                  )}
                  {c.refunded_cents > 0 && (
                    <p className="mt-1 text-[11px] font-medium text-stone-400">
                      {formatMoney(c.refunded_cents, c.currency)} refunded
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  );
}
