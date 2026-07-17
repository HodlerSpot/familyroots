"use client";

import { useState } from "react";
import { AdminBroadcastResult, adminApi, ApiError } from "@/lib/api";
import { AdminShell } from "@/components/admin/shell";
import { Button, Card, ErrorNote, Input, Label, Modal } from "@/components/ui";

// Hard limits from docs/brand/notifications-copy.md (push title 50 / body 120).
const TITLE_MAX = 50;
const BODY_MAX = 120;

export default function AdminBroadcastPage() {
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [url, setUrl] = useState("");
  const [includeEmail, setIncludeEmail] = useState(false);

  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [reach, setReach] = useState<AdminBroadcastResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [sent, setSent] = useState<AdminBroadcastResult | null>(null);

  const canCompose = title.trim().length > 0 && body.trim().length > 0;

  function payload(dryRun: boolean) {
    return {
      title: title.trim(),
      body: body.trim(),
      url: url.trim() || undefined,
      include_email: includeEmail,
      dry_run: dryRun,
    };
  }

  async function checkReach() {
    setError("");
    setBusy(true);
    try {
      const res = await adminApi.broadcast(payload(true));
      setReach(res);
      setConfirmOpen(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't check the reach just now.");
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    setError("");
    setBusy(true);
    try {
      const res = await adminApi.broadcast(payload(false));
      setSent(res);
      setConfirmOpen(false);
    } catch (err) {
      setConfirmOpen(false);
      setError(err instanceof ApiError ? err.message : "We couldn't send that just now.");
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setTitle("");
    setBody("");
    setUrl("");
    setIncludeEmail(false);
    setReach(null);
    setSent(null);
    setError("");
  }

  if (sent) {
    return (
      <AdminShell>
        <Card className="mx-auto max-w-lg text-center">
          <div className="text-4xl">📣</div>
          <h1 className="mt-2 text-xl font-bold text-emerald-900">Your announcement is on its way.</h1>
          <p className="mt-2 text-stone-600">
            It reached {countText(sent.bell)} in the app
            {sent.push !== undefined ? `, ${countText(sent.push)} by push` : ""}
            {includeEmail && sent.email !== undefined ? `, and ${countText(sent.email)} by email` : ""}.
          </p>
          <div className="mt-6">
            <Button onClick={reset}>Write another</Button>
          </div>
        </Card>
      </AdminShell>
    );
  }

  return (
    <AdminShell>
      <div className="grid gap-6 lg:grid-cols-2">
        {/* --- Composer --- */}
        <Card>
          <h2 className="text-lg font-semibold text-emerald-900">New announcement</h2>
          <p className="mt-1 text-sm text-stone-600">
            This goes to every family on FutureRoots. Everyone sees it in their notification bell;
            people who&apos;ve opted out of announcements simply won&apos;t be interrupted.
          </p>

          {error && (
            <div className="mt-4">
              <ErrorNote>{error}</ErrorNote>
            </div>
          )}

          <div className="mt-5 space-y-4">
            <div>
              <div className="flex items-baseline justify-between">
                <Label htmlFor="broadcast-title">Title</Label>
                <span className={`text-xs ${title.length > TITLE_MAX ? "text-red-600" : "text-stone-400"}`}>
                  {title.length}/{TITLE_MAX}
                </span>
              </div>
              <Input
                id="broadcast-title"
                value={title}
                maxLength={TITLE_MAX}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="A short, warm headline"
              />
            </div>

            <div>
              <div className="flex items-baseline justify-between">
                <Label htmlFor="broadcast-body">Message</Label>
                <span className={`text-xs ${body.length > BODY_MAX ? "text-red-600" : "text-stone-400"}`}>
                  {body.length}/{BODY_MAX}
                </span>
              </div>
              <textarea
                id="broadcast-body"
                value={body}
                maxLength={BODY_MAX}
                onChange={(e) => setBody(e.target.value)}
                rows={3}
                placeholder="Say what's new in a sentence or two."
                className="w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none"
              />
            </div>

            <div>
              <Label htmlFor="broadcast-url">Link (optional)</Label>
              <Input
                id="broadcast-url"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
                placeholder="/family"
              />
              <p className="mt-1 text-xs text-stone-500">
                Where tapping the notification takes people. Leave blank for the family feed.
              </p>
            </div>

            <label className="flex cursor-pointer items-start gap-3 rounded-lg bg-stone-50 p-3">
              <input
                type="checkbox"
                checked={includeEmail}
                onChange={(e) => setIncludeEmail(e.target.checked)}
                className="mt-1 h-5 w-5 shrink-0 rounded border-stone-300 text-emerald-600 focus:ring-emerald-500"
              />
              <span>
                <span className="block font-medium text-stone-900">Send as an email</span>
                <span className="mt-0.5 block text-sm text-amber-700">
                  Email can&apos;t be unsent once it goes out. Give it one more read before you send.
                </span>
              </span>
            </label>

            <Button onClick={checkReach} disabled={!canCompose || busy} className="w-full">
              {busy ? "Checking…" : "Check who this reaches"}
            </Button>
          </div>
        </Card>

        {/* --- Live preview --- */}
        <div className="space-y-4">
          <Card>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              How the push looks
            </h3>
            <div className="mt-3 flex items-start gap-3 rounded-xl border border-stone-200 bg-stone-50 p-3">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/logo-mark.png" alt="" className="h-10 w-10 shrink-0 rounded-lg" />
              <div className="min-w-0">
                <p className="text-xs font-medium text-stone-500">FutureRoots · now</p>
                <p className="mt-0.5 font-semibold text-stone-900">
                  {title.trim() || "Your title"}
                </p>
                <p className="text-sm text-stone-600">
                  {body.trim() || "Your message will appear here."}
                </p>
              </div>
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold uppercase tracking-wide text-stone-500">
              How the bell looks
            </h3>
            <div className="mt-3 rounded-xl border border-stone-200 bg-emerald-50/40 px-4 py-3">
              <div className="flex items-start justify-between gap-3">
                <p className="min-w-0 text-sm font-semibold text-stone-900">
                  {title.trim() || "Your title"}
                </p>
                <span className="shrink-0 text-xs text-stone-400">Just now</span>
              </div>
              <p className="mt-0.5 text-sm text-stone-600">
                {body.trim() || "Your message will appear here."}
              </p>
            </div>
          </Card>
        </div>
      </div>

      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="Send this to your families?"
      >
        <p className="text-stone-700">
          This reaches {countText(reach?.push)} by push and {countText(reach?.email)} by email. Once
          it sends, it can&apos;t be recalled.
        </p>
        {includeEmail && (
          <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Email can&apos;t be unsent once it goes out. Give it one more read before you send.
          </p>
        )}
        <div className="mt-6 flex justify-end gap-3">
          <Button variant="soft" onClick={() => setConfirmOpen(false)} disabled={busy}>
            Not yet
          </Button>
          <Button onClick={send} disabled={busy}>
            {busy ? "Sending…" : "Send now"}
          </Button>
        </div>
      </Modal>
    </AdminShell>
  );
}

/** "3 people" / "1 person" / "0 people", defensive against a missing count. */
function countText(n: number | undefined): string {
  const value = typeof n === "number" ? n : 0;
  return `${value} ${value === 1 ? "person" : "people"}`;
}
