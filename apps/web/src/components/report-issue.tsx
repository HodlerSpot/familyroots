"use client";

// A quiet "Report an issue" affordance for signed-in family members on the
// main site. Submissions land in the same admin bug-reports queue as testnet
// reports (as a user-reported issue). Hidden on the testnet build, where the
// gamified Quests panel already has a bug reporter.

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { api, ApiError, getToken } from "@/lib/api";
import { Button } from "@/components/ui";

const IS_TESTNET = process.env.NEXT_PUBLIC_TESTNET === "1";

export function ReportIssue() {
  const pathname = usePathname();
  const [authed, setAuthed] = useState(false);
  const [open, setOpen] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setAuthed(Boolean(getToken()));
  }, [pathname]);

  // Not on the testnet build, not on the landing page, only when signed in
  if (IS_TESTNET || pathname === "/" || !authed) return null;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api.reportIssue(title.trim(), body.trim());
      setSent(true);
      setTitle("");
      setBody("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => {
          setOpen(true);
          setSent(false);
        }}
        className="fixed bottom-5 right-5 z-40 rounded-full border border-stone-300 bg-white px-4 py-2.5 text-sm font-medium text-stone-600 shadow-md hover:border-emerald-400 hover:text-emerald-800"
      >
        Report an issue
      </button>

      {open && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4"
          onClick={() => setOpen(false)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="mb-1 flex items-start justify-between">
              <h2 className="text-xl font-bold text-emerald-900">Report an issue</h2>
              <button onClick={() => setOpen(false)} className="text-2xl leading-none text-stone-400" aria-label="Close">
                ×
              </button>
            </div>
            {sent ? (
              <div className="py-4 text-center">
                <div className="text-4xl">🙏</div>
                <p className="mt-2 text-stone-700">
                  Thank you. Our team will take a look. You can close this now.
                </p>
                <Button className="mt-4 w-full" onClick={() => setOpen(false)}>
                  Done
                </Button>
              </div>
            ) : (
              <>
                <p className="mb-4 text-sm text-stone-600">
                  Something not working right? Tell us what happened and we&apos;ll look into it.
                </p>
                <form onSubmit={submit} className="space-y-3">
                  <input
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                    placeholder="What went wrong?"
                    maxLength={200}
                    required
                    className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
                  />
                  <textarea
                    value={body}
                    onChange={(e) => setBody(e.target.value)}
                    placeholder="What were you doing, and what did you expect to happen?"
                    maxLength={5000}
                    rows={4}
                    required
                    className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
                  />
                  {error && <p className="text-sm text-red-600">{error}</p>}
                  <Button type="submit" disabled={busy || !title.trim() || !body.trim()} className="w-full">
                    {busy ? "Sending…" : "Send report"}
                  </Button>
                </form>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
