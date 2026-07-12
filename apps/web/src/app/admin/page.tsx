"use client";

import { useEffect, useState } from "react";
import { AdminOverview, adminApi, formatMoney } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

function Stat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <Card className={accent ? "bg-emerald-50" : ""}>
      <div className="text-3xl font-extrabold tabular-nums text-emerald-900">{value}</div>
      <div className="mt-1 text-sm text-stone-500">{label}</div>
    </Card>
  );
}

function ago(iso: string): string {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 3600) return `${Math.max(1, Math.floor(s / 60))}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

export default function AdminOverviewPage() {
  const [data, setData] = useState<AdminOverview | null>(null);

  useEffect(() => {
    adminApi.overview().then(setData).catch(() => {});
  }, []);

  return (
    <AdminShell>
      {data && (
        <div className="space-y-6">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Families" value={data.families.toLocaleString()} />
            <Stat label="Children" value={data.children.toLocaleString()} />
            <Stat label="Registered users" value={data.users.toLocaleString()} />
            <Stat
              label="Contributed to futures"
              value={formatMoney(data.contributed_cents)}
              accent
            />
            <Stat label="Contributions" value={data.contributions.toLocaleString()} />
            <Stat label="Contributors" value={data.contributors.toLocaleString()} />
            <Stat label="Admins" value={data.admins.toLocaleString()} />
            <Stat label="Bug reports pending" value={data.pending_bugs.toLocaleString()} />
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <div>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
                Recent signups
              </h2>
              <Card className="p-0">
                <ul className="divide-y divide-stone-100">
                  {data.recent_signups.map((u) => (
                    <li key={u.id} className="flex items-center justify-between px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-stone-900">{u.display_name}</p>
                        <p className="truncate text-xs text-stone-500">{u.email}</p>
                      </div>
                      <span className="shrink-0 text-xs text-stone-400">{ago(u.created_at)}</span>
                    </li>
                  ))}
                  {data.recent_signups.length === 0 && (
                    <li className="px-4 py-6 text-center text-sm text-stone-500">No users yet.</li>
                  )}
                </ul>
              </Card>
            </div>

            <div>
              <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-stone-500">
                Recent contributions
              </h2>
              <Card className="p-0">
                <ul className="divide-y divide-stone-100">
                  {data.recent_contributions.map((c) => (
                    <li key={c.id} className="flex items-center justify-between px-4 py-2.5">
                      <div className="min-w-0">
                        <p className="truncate text-sm text-stone-900">
                          <span className="font-medium">{c.contributor_name}</span> to{" "}
                          {c.child_name}
                        </p>
                        <p className="text-xs text-stone-400">{ago(c.created_at)}</p>
                      </div>
                      <span className="shrink-0 font-bold tabular-nums text-emerald-800">
                        {formatMoney(c.amount_cents, c.currency)}
                      </span>
                    </li>
                  ))}
                  {data.recent_contributions.length === 0 && (
                    <li className="px-4 py-6 text-center text-sm text-stone-500">
                      No contributions yet.
                    </li>
                  )}
                </ul>
              </Card>
            </div>
          </div>
        </div>
      )}
    </AdminShell>
  );
}
