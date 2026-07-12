"use client";

import { useEffect, useState } from "react";
import { AdminContribution, adminApi, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

const CHIP: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

export default function AdminContributionsPage() {
  const [rows, setRows] = useState<AdminContribution[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    adminApi
      .contributions()
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, []);

  return (
    <AdminShell>
      <div className="mb-4 text-sm text-stone-500">{total} contributions</div>
      <Card className="overflow-hidden p-0">
        <div className="hidden items-center gap-4 border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-500 sm:flex">
          <span className="flex-1">Contributor</span>
          <span className="w-32">For child</span>
          <span className="w-24 text-center">Status</span>
          <span className="w-24 text-right">Amount</span>
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((c) => (
            <li key={c.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <p className="min-w-0 flex-1 truncate font-medium text-stone-900">
                {c.contributor_name}
              </p>
              <p className="w-32 truncate text-sm text-stone-600">{c.child_name}</p>
              <span className="w-24 text-center">
                <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${CHIP[c.status] ?? "bg-stone-100 text-stone-600"}`}>
                  {c.status}
                </span>
              </span>
              <span className="w-24 text-right font-bold tabular-nums text-emerald-800">
                {formatMoney(c.amount_cents, c.currency)}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No contributions yet.</li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
