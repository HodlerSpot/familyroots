"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { AdminFamilyDetail, adminApi, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

const STATUS_CHIP: Record<string, string> = {
  succeeded: "bg-emerald-100 text-emerald-800",
  pending: "bg-amber-100 text-amber-800",
  failed: "bg-red-100 text-red-700",
  refunded: "bg-stone-200 text-stone-600",
};

function ago(iso: string): string {
  return new Date(iso).toLocaleDateString();
}

export default function AdminFamilyDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [f, setF] = useState<AdminFamilyDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    adminApi.family(id).then(setF).catch(() => setError("Couldn't load this family."));
  }, [id]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <AdminShell>
      <a href="/admin/families" className="text-sm text-stone-500 underline">
        Back to families
      </a>
      {error && <Card className="mt-4">{error}</Card>}
      {f && (
        <div className="mt-4 space-y-6">
          <Card className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h2 className="text-2xl font-bold text-stone-900">{f.name}</h2>
              <p className="text-sm text-stone-400">
                Created {ago(f.created_at)} · {f.members.length} members · {f.children.length} children
              </p>
            </div>
            <div className="text-right">
              <div className="text-2xl font-extrabold tabular-nums text-emerald-900">
                {formatMoney(f.fund_cents)}
              </div>
              <div className="text-sm text-stone-500">total future funds</div>
            </div>
          </Card>

          <section>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
              Children
            </h3>
            <Card className="p-0">
              <ul className="divide-y divide-stone-100">
                {f.children.map((c) => (
                  <li key={c.id} className="flex items-center justify-between px-4 py-2.5">
                    <span className="font-medium text-stone-900">{c.first_name}</span>
                    <span className="font-bold tabular-nums text-emerald-800">
                      {formatMoney(c.fund_cents)}
                    </span>
                  </li>
                ))}
                {f.children.length === 0 && (
                  <li className="px-4 py-6 text-center text-sm text-stone-500">No children yet.</li>
                )}
              </ul>
            </Card>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
              Members
            </h3>
            <Card className="p-0">
              <ul className="divide-y divide-stone-100">
                {f.members.map((m) => (
                  <li key={m.user_id} className="flex items-center gap-4 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <a href={`/admin/users/${m.user_id}`} className="font-medium text-emerald-800 underline">
                        {m.display_name}
                      </a>
                      <p className="truncate text-xs text-stone-500">{m.email}</p>
                    </div>
                    {m.disabled && (
                      <span className="rounded-full bg-stone-200 px-2 py-0.5 text-[10px] font-semibold uppercase text-stone-600">
                        disabled
                      </span>
                    )}
                    <span className="text-sm capitalize text-stone-500">{m.role}</span>
                  </li>
                ))}
              </ul>
            </Card>
          </section>

          <section>
            <h3 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
              Contribution history ({f.contributions.length})
            </h3>
            <Card className="p-0">
              <ul className="divide-y divide-stone-100">
                {f.contributions.map((c) => (
                  <li key={c.id} className="flex items-center gap-4 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm text-stone-900">
                        {c.contributor_id ? (
                          <a href={`/admin/users/${c.contributor_id}`} className="font-medium text-emerald-800 underline">
                            {c.contributor_name}
                          </a>
                        ) : (
                          <span className="font-medium">{c.contributor_name}</span>
                        )}{" "}
                        to {c.child_name}
                      </p>
                      <p className="text-xs text-stone-400">{ago(c.created_at)}</p>
                    </div>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_CHIP[c.status] ?? "bg-stone-100 text-stone-600"}`}>
                      {c.status}
                    </span>
                    <span className="w-24 text-right font-bold tabular-nums text-emerald-800">
                      {formatMoney(c.amount_cents, c.currency)}
                    </span>
                  </li>
                ))}
                {f.contributions.length === 0 && (
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
