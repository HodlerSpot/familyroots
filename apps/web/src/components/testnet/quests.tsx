"use client";

// Floating "Quests" button + slide-in panel: the tester's live scorecard.
// Polls every 5 seconds so points tick up in near real time as actions land.

import { useCallback, useEffect, useState } from "react";
import { QuestBoard, testnetApi } from "./api";

function shortWallet(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

export function QuestsButton() {
  const [open, setOpen] = useState(false);
  const [board, setBoard] = useState<QuestBoard | null>(null);
  const [savingName, setSavingName] = useState(false);
  const [nameDraft, setNameDraft] = useState("");

  const refresh = useCallback(async () => {
    try {
      setBoard(await testnetApi.quests());
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
              <div>
                <h2 className="text-2xl font-bold text-emerald-900">Your quests</h2>
                <p className="text-sm text-stone-500">
                  {board?.display_name ??
                    (board ? shortWallet(board.wallet_address) : "Loading…")}
                </p>
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
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
