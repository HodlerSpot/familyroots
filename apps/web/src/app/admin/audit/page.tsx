"use client";

import { useEffect, useState } from "react";
import { AdminAuditRow, adminApi } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Card } from "@/components/ui";

const ACTION_LABEL: Record<string, string> = {
  bug_verify: "verified a bug",
  bug_reject: "rejected a bug",
  bug_verified: "verified a bug",
  role_changed: "changed a role",
  impersonate: "viewed as a user",
  contribution_refunded: "refunded a contribution",
  contributions_exported: "exported contributions",
};

export default function AdminAuditPage() {
  const [rows, setRows] = useState<AdminAuditRow[]>([]);
  const [total, setTotal] = useState(0);

  useEffect(() => {
    adminApi
      .audit()
      .then((p) => {
        setRows(p.items);
        setTotal(p.total);
      })
      .catch(() => {});
  }, []);

  return (
    <AdminShell>
      <div className="mb-4 text-sm text-stone-500">
        {total} logged actions. Every consequential admin action is recorded here.
      </div>
      <Card className="p-0">
        <ul className="divide-y divide-stone-100">
          {rows.map((r) => (
            <li key={r.id} className="flex items-start justify-between gap-4 px-4 py-3">
              <div className="min-w-0">
                <p className="text-sm text-stone-900">
                  <span className="font-medium">{r.admin_name}</span>{" "}
                  {ACTION_LABEL[r.action] ?? r.action}
                  {r.target ? <span className="text-stone-400"> · {r.target}</span> : null}
                </p>
                {Object.keys(r.detail).length > 0 && (
                  <p className="mt-0.5 truncate font-mono text-xs text-stone-400">
                    {JSON.stringify(r.detail)}
                  </p>
                )}
              </div>
              <span className="shrink-0 text-xs text-stone-400">
                {new Date(r.created_at).toLocaleString()}
              </span>
            </li>
          ))}
          {rows.length === 0 && (
            <li className="px-4 py-8 text-center text-sm text-stone-500">No actions logged yet.</li>
          )}
        </ul>
      </Card>
    </AdminShell>
  );
}
