"use client";

import { useCallback, useEffect, useState } from "react";
import { AdminContribution, adminApi, downloadCsv, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Button, Card } from "@/components/ui";

const CHIP: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

const STATUSES = ["", "succeeded", "pending", "failed", "refunded"];

export default function AdminContributionsPage() {
  const [rows, setRows] = useState<AdminContribution[]>([]);
  const [total, setTotal] = useState(0);
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(() => {
    adminApi
      .contributions(q || undefined, status || undefined)
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, [q, status]);

  useEffect(() => {
    const t = setTimeout(load, 250);
    return () => clearTimeout(t);
  }, [load]);

  async function refund(c: AdminContribution) {
    const remaining = c.amount_cents - c.refunded_cents;
    const input = prompt(
      `Refund amount for ${c.contributor_name} (in dollars, up to ${formatMoney(remaining, c.currency)}). ` +
        `Leave blank to refund the full remaining amount.`,
      ""
    );
    if (input === null) return; // cancelled
    let amountCents: number | undefined;
    if (input.trim() !== "") {
      const dollars = parseFloat(input);
      if (!(dollars > 0)) return;
      amountCents = Math.round(dollars * 100);
      if (amountCents > remaining) {
        alert(`That's more than the ${formatMoney(remaining, c.currency)} remaining.`);
        return;
      }
    }
    setBusyId(c.id);
    try {
      await adminApi.refund(c.id, amountCents);
      load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <AdminShell>
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Search contributor or child"
          className="w-56 rounded-lg border border-stone-300 px-3 py-2 text-sm"
        />
        <select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          className="rounded-lg border border-stone-300 px-3 py-2 text-sm"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "" ? "All statuses" : s}
            </option>
          ))}
        </select>
        <span className="text-sm text-stone-500">{total} total</span>
        <Button
          variant="soft"
          className="ml-auto"
          onClick={() =>
            downloadCsv(
              adminApi.contributionsCsvUrl(q || undefined, status || undefined),
              "futureroots-contributions.csv"
            )
          }
        >
          Download CSV
        </Button>
      </div>

      <Card className="overflow-hidden p-0">
        <div className="hidden items-center gap-4 border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-500 sm:flex">
          <span className="flex-1">Contributor</span>
          <span className="w-28">For child</span>
          <span className="w-24 text-center">Status</span>
          <span className="w-24 text-right">Amount</span>
          <span className="w-20" />
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <p className="min-w-0 flex-1 truncate font-medium text-stone-900">
                {c.contributor_name}
              </p>
              <p className="w-28 truncate text-sm text-stone-600">{c.child_name}</p>
              <span className="w-24 text-center">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${CHIP[c.status] ?? "bg-stone-100 text-stone-600"}`}>
                  {c.status}
                </span>
              </span>
              <span className="w-24 text-right tabular-nums">
                <span className="font-bold text-emerald-800">
                  {formatMoney(c.amount_cents, c.currency)}
                </span>
                {c.refunded_cents > 0 && (
                  <span className="block text-[11px] font-medium text-stone-400">
                    {formatMoney(c.refunded_cents, c.currency)} refunded
                  </span>
                )}
              </span>
              <span className="w-20 text-right">
                {c.status === "succeeded" && (
                  <button
                    onClick={() => refund(c)}
                    disabled={busyId === c.id}
                    className="text-xs font-medium text-red-600 underline hover:text-red-700 disabled:opacity-50"
                  >
                    {c.refunded_cents > 0 ? "Refund more" : "Refund"}
                  </button>
                )}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No contributions found.</li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
