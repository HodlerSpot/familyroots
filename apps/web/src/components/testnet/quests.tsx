"use client";

// Floating "Quests" button + slide-in panel: the tester's live scorecard.
// Polls every 5 seconds so points tick up in near real time as actions land.

import { useCallback, useEffect, useRef, useState } from "react";
import { BugReport, QuestBoard, testnetApi } from "./api";
import { Avatar } from "./identicon";

function shortWallet(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

const BUG_STATUS_CHIP: Record<BugReport["status"], { label: string; className: string }> = {
  pending: { label: "In review", className: "bg-amber-100 text-amber-800" },
  verified: { label: "Verified +250", className: "bg-emerald-100 text-emerald-800" },
  rejected: { label: "Not a bug", className: "bg-stone-200 text-stone-600" },
};

export function QuestsButton() {
  const [open, setOpen] = useState(false);
  const [board, setBoard] = useState<QuestBoard | null>(null);
  const [savingName, setSavingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");
  const [bugs, setBugs] = useState<BugReport[]>([]);
  const [bugTitle, setBugTitle] = useState("");
  const [bugBody, setBugBody] = useState("");
  const [submittingBug, setSubmittingBug] = useState(false);
  const [bugError, setBugError] = useState<string | null>(null);
  const [pastedImage, setPastedImage] = useState<File | null>(null);
  const bugImageRef = useRef<HTMLInputElement>(null);

  // Paste a screenshot straight into the report (Cmd/Ctrl+V) without saving a file
  function onBugPaste(e: React.ClipboardEvent) {
    const item = Array.from(e.clipboardData.items).find((i) => i.type.startsWith("image/"));
    if (!item) return;
    const file = item.getAsFile();
    if (file) {
      e.preventDefault();
      setPastedImage(file);
    }
  }

  const refresh = useCallback(async () => {
    try {
      const [nextBoard, nextBugs] = await Promise.all([
        testnetApi.quests(),
        testnetApi.myBugs(),
      ]);
      setBoard(nextBoard);
      setBugs(nextBugs);
    } catch {
      // transient; the next poll retries
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  async function saveName(e: React.FormEvent) {
    e.preventDefault();
    if (!nameDraft.trim()) return;
    setSavingName(true);
    try {
      await testnetApi.setProfile(nameDraft.trim());
      setNameDraft("");
      await refresh();
    } finally {
      setSavingName(false);
    }
  }

  async function submitBug(e: React.FormEvent) {
    e.preventDefault();
    if (!bugTitle.trim() || !bugBody.trim()) return;
    setSubmittingBug(true);
    setBugError(null);
    try {
      const file = pastedImage ?? bugImageRef.current?.files?.[0];
      const media_id = file ? await testnetApi.uploadBugImage(file) : undefined;
      await testnetApi.submitBug({ title: bugTitle.trim(), body: bugBody.trim(), media_id });
      setBugTitle("");
      setBugBody("");
      setPastedImage(null);
      if (bugImageRef.current) bugImageRef.current.value = "";
      await refresh();
    } catch (err) {
      setBugError(err instanceof Error ? err.message : "Something went wrong. Please try again");
    } finally {
      setSubmittingBug(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen((v) => !v)}
        className="fixed bottom-5 right-5 z-40 flex items-center gap-2 rounded-full bg-emerald-700 px-5 py-3 text-sm font-bold text-white shadow-lg transition-colors hover:bg-emerald-800"
        aria-label="Open quests panel"
      >
        🎮 Quests
        {board && (
          <span className="rounded-full bg-white/20 px-2 py-0.5 tabular-nums">
            {board.total_points}
          </span>
        )}
      </button>

      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={() => setOpen(false)}>
          <div
            className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-start justify-between">
              <div className="flex items-center gap-3">
                {board && (
                  <Avatar seed={board.wallet_address} src={board.avatar_url} size={44} />
                )}
                <div>
                  <h2 className="text-2xl font-bold text-emerald-900">Your quests</h2>
                  <p className="text-sm text-stone-500">
                    {board?.x_username ??
                      board?.display_name ??
                      (board ? shortWallet(board.wallet_address) : "Loading…")}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-2xl leading-none text-stone-400 hover:text-stone-600"
                aria-label="Close"
              >
                ×
              </button>
            </div>

            {board && (
              <>
                <div className="mt-4 rounded-2xl bg-emerald-50 p-5 text-center">
                  <div className="text-4xl font-extrabold tabular-nums text-emerald-900">
                    {board.total_points}
                  </div>
                  <div className="text-sm text-emerald-800">points earned</div>
                  <a
                    href="/leaderboard"
                    className="mt-2 inline-block text-sm font-medium text-emerald-700 underline"
                  >
                    See the leaderboard
                  </a>
                </div>

                <p className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-900">
                  Tip: to earn the contribution quest, a parent sets up a child&apos;s Future Fund
                  first (the &ldquo;Open a future fund&rdquo; quest) — then any family member can send a gift.
                </p>

                {!board.display_name && (
                  <form onSubmit={saveName} className="mt-4 flex gap-2">
                    <input
                      value={nameDraft}
                      onChange={(e) => setNameDraft(e.target.value)}
                      placeholder="Pick a leaderboard name"
                      maxLength={40}
                      className="flex-1 rounded-lg border border-stone-300 px-3 py-2 text-sm"
                    />
                    <button
                      type="submit"
                      disabled={savingName}
                      className="rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white disabled:opacity-50"
                    >
                      Save
                    </button>
                  </form>
                )}

                <ul className="mt-5 space-y-2">
                  {board.quests.map((q) => {
                    const done = q.times_completed > 0;
                    const maxedToday = q.completed_today >= q.daily_cap;
                    return (
                      <li
                        key={q.action}
                        className={`rounded-xl border p-3 ${
                          done ? "border-emerald-200 bg-emerald-50/40" : "border-stone-200"
                        }`}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="font-semibold text-stone-900">
                              <span className="mr-1">{done ? "✅" : "⬜"}</span>
                              {q.label}
                            </p>
                            <p className="mt-0.5 text-xs text-stone-500">{q.hint}</p>
                          </div>
                          <div className="shrink-0 text-right">
                            <div className="font-bold tabular-nums text-emerald-700">
                              +{q.points}
                            </div>
                            {q.points_earned > 0 && (
                              <div className="text-xs text-stone-400 tabular-nums">
                                {q.points_earned} earned
                              </div>
                            )}
                          </div>
                        </div>
                        {q.once ? (
                          <p className="mt-1 text-[11px] uppercase tracking-wide text-stone-400">
                            One time
                          </p>
                        ) : (
                          <p className="mt-1 text-[11px] uppercase tracking-wide text-stone-400">
                            {maxedToday
                              ? "Daily max reached, back tomorrow"
                              : `Up to ${q.daily_cap} a day`}
                          </p>
                        )}
                      </li>
                    );
                  })}
                </ul>

                <div className="mt-6 rounded-2xl border border-emerald-200 bg-emerald-50/40 p-4">
                  <h3 className="font-semibold text-emerald-900">Found a bug?</h3>
                  <p className="mt-0.5 text-xs text-stone-500">
                    Tell us what broke. When our team confirms it is a real bug, you earn 250
                    points. Thank you for helping us build something better.
                  </p>
                  <form onSubmit={submitBug} onPaste={onBugPaste} className="mt-3 space-y-2">
                    <input
                      value={bugTitle}
                      onChange={(e) => setBugTitle(e.target.value)}
                      placeholder="What went wrong?"
                      maxLength={200}
                      className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
                    />
                    <textarea
                      value={bugBody}
                      onChange={(e) => setBugBody(e.target.value)}
                      placeholder="Steps to see it, and what you expected instead"
                      maxLength={5000}
                      rows={3}
                      className="w-full rounded-lg border border-stone-300 px-3 py-2 text-sm"
                    />
                    {pastedImage ? (
                      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50/60 px-3 py-2">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img
                          src={URL.createObjectURL(pastedImage)}
                          alt="pasted screenshot"
                          className="h-10 w-10 rounded-md object-cover"
                        />
                        <span className="flex-1 text-xs text-emerald-900">Screenshot pasted</span>
                        <button
                          type="button"
                          onClick={() => setPastedImage(null)}
                          className="text-xs text-stone-500 underline"
                        >
                          remove
                        </button>
                      </div>
                    ) : (
                      <label className="block text-xs text-stone-500">
                        Add a screenshot (optional): choose a file, or paste one with Ctrl/Cmd+V
                        <input
                          ref={bugImageRef}
                          type="file"
                          accept="image/*"
                          className="mt-1 block w-full text-xs text-stone-600 file:mr-2 file:rounded-md file:border-0 file:bg-emerald-100 file:px-2 file:py-1 file:text-emerald-800"
                        />
                      </label>
                    )}
                    {bugError && <p className="text-xs text-red-600">{bugError}</p>}
                    <button
                      type="submit"
                      disabled={submittingBug || !bugTitle.trim() || !bugBody.trim()}
                      className="w-full rounded-lg bg-emerald-700 px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-emerald-800 disabled:opacity-50"
                    >
                      {submittingBug ? "Sending…" : "Send bug report"}
                    </button>
                  </form>

                  {bugs.length > 0 && (
                    <ul className="mt-4 space-y-2">
                      {bugs.map((bug) => {
                        const chip = BUG_STATUS_CHIP[bug.status];
                        return (
                          <li
                            key={bug.id}
                            className="flex items-start gap-3 rounded-xl border border-stone-200 bg-white p-3"
                          >
                            {bug.media_id && (
                              // eslint-disable-next-line @next/next/no-img-element
                              <img
                                src={testnetApi.mediaUrl(bug.media_id)}
                                alt="bug screenshot"
                                className="h-10 w-10 shrink-0 rounded-md object-cover"
                              />
                            )}
                            <p className="min-w-0 flex-1 truncate text-sm font-medium text-stone-800">
                              {bug.title}
                            </p>
                            <span
                              className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-semibold ${chip.className}`}
                            >
                              {chip.label}
                            </span>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
