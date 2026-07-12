"use client";

import { useEffect, useState } from "react";
import { AdminFamilyRow, adminApi, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

export default function AdminFamiliesPage() {
  const [rows, setRows] = useState<AdminFamilyRow[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    adminApi
      .families()
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, []);

  return (
    <AdminShell>
      <div className="mb-4 text-sm text-stone-500">{total} families</div>
      <Card className="overflow-hidden p-0">
        <div className="hidden items-center gap-4 border-b border-stone-200 bg-stone-50 px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-stone-500 sm:flex">
          <span className="flex-1">Family</span>
          <span className="w-20 text-center">Members</span>
          <span className="w-20 text-center">Children</span>
          <span className="w-28 text-right">Future fund</span>
        </div>
        <ul className="divide-y divide-stone-100">
          {rows.map((f) => (
            <li key={f.id} className="flex flex-wrap items-center gap-4 px-4 py-3">
              <p className="min-w-0 flex-1 truncate font-medium text-stone-900">{f.name}</p>
              <span className="w-20 text-center tabular-nums text-stone-700">{f.member_count}</span>
              <span className="w-20 text-center tabular-nums text-stone-700">{f.child_count}</span>
              <span className="w-28 text-right font-bold tabular-nums text-emerald-800">
                {formatMoney(f.fund_cents)}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No families yet.</li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
