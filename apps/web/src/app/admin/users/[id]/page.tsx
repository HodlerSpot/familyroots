"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AdminUserDetail, adminApi, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

const STATUS_CHIP: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

export default function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [u, setU] = useState<AdminUserDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    adminApi.user(id).then(setU).catch(() => setError("Couldn't load this user."));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AdminShell>
      <a href="/admin/users" className="text-sm text-stone-500 underline">
        Back to users
      </a>
      {error && <Card className="mt-4">{error}</Card>}
      {u && (
        <div className="mt-4 space-y-6">
          <Card>
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h2 className="flex items-center gap-2 text-2xl font-bold text-stone-900">
                  {u.display_name}
                  {u.role === "admin" && (
                    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-xs font-semibold text-emerald-800">
                      admin
                    </span>
                  )}
                  {u.disabled && (
                    <span className="rounded-full bg-stone-200 px-2 py-0.5 text-xs font-semibold text-stone-600">
                      disabled
                    </span>
                  )}
                </h2>
                <p className="text-stone-500">{u.email}</p>
              </div>
              <p className="text-sm text-stone-400">
                Joined {new Date(u.created_at).toLocaleDateString()}
              </p>
            </div>
          </Card>

          <section>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
              Families ({u.families.length})
            </h3>
            <Card className="p-0">
              <ul className="divide-y divide-stone-100">
                {u.families.map((f) => (
                  <li key={f.id} className="flex items-center justify-between px-4 py-2.5">
                    <a href={`/admin/families/${f.id}`} className="font-medium text-emerald-800 underline">
                      {f.name}
                    </a>
                    <span className="text-sm capitalize text-stone-500">{f.role}</span>
                  </li>
                ))}
                {u.families.length === 0 && (
                  <li className="px-4 py-6 text-center text-sm text-stone-500">
                    Not part of any family.
                  </li>
                )}
              </ul>
            </Card>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
              Contributions ({u.contributions.length})
            </h3>
            <Card className="p-0">
              <ul className="divide-y divide-stone-100">
                {u.contributions.map((c) => (
                  <li key={c.id} className="flex items-center gap-4 px-4 py-2.5">
                    <span className="flex-1 truncate text-sm text-stone-700">
                      to {c.child_name}
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CHIP[c.status] ?? "bg-stone-100 text-stone-600"}`}>
                      {c.status}
                    </span>
                    <span className="w-24 text-right font-bold tabular-nums text-emerald-800">
                      {formatMoney(c.amount_cents, c.currency)}
                    </span>
                  </li>
                ))}
                {u.contributions.length === 0 && (
                  <li className="px-4 py-6 text-center text-sm text-stone-500">
                    No contributions yet.
                  </li>
                )}
              </ul>
            </Card>
          </section>
        </div>
      )}
    </AdminShell>
  );
}
