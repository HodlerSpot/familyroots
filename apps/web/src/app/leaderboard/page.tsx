"use client";

// Tester leaderboard. Only reachable on the testnet build; on the family
// product this route renders nothing meaningful (the API endpoint 404s).
// Polls every 5 seconds so ranks shift in near real time.

import { useCallback, useEffect, useState } from "react";
import { Leaderboard, testnetApi } from "@/components/testnet/api";
import { Avatar } from "@/components/testnet/identicon";
import { Card } from "@/components/ui";

const MEDALS = ["🥇", "🥈", "🥉"];

export default function LeaderboardPage() {
  const [board, setBoard] = useState<Leaderboard | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      setBoard(await testnetApi.leaderboard());
      setError("");
    } catch {
      setError("The leaderboard is only available on the FutureRoots testnet.");
    }
  }, []);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, 5000);
    return () => clearInterval(id);
  }, [refresh]);

  const onBoard = board?.entries.some((e) => e.is_me) ?? false;

  return (
    <div>
      {/* Title block, with clear separation from the board below */}
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold text-emerald-900">Tester leaderboard 🏆</h1>
          <p className="max-w-lg text-stone-600">
            Every action you test earns points. Thank you for helping families keep their
            memories safe.
          </p>
        </div>
        <a
          href="/family"
          className="shrink-0 rounded-lg border border-stone-200 px-3 py-1.5 text-sm font-medium text-stone-600 hover:border-emerald-400 hover:text-emerald-800"
        >
          Back to testing
        </a>
      </div>

      {error && <Card className="mt-8">{error}</Card>}

      {board && (
        <Card className="mt-8 overflow-hidden p-0">
          {/* Column titles */}
          <div className="flex items-center gap-4 border-b border-stone-200 bg-stone-50 px-5 py-3 text-xs font-semibold uppercase tracking-wide text-stone-500">
            <span className="w-8 text-center">Rank</span>
            <span className="w-9" aria-hidden />
            <span className="flex-1">Tester</span>
            <span className="w-20 text-right">Points</span>
          </div>

          <ul className="divide-y divide-stone-100">
            {board.entries.map((e) => (
              <li
                key={e.rank}
                className={`flex items-center gap-4 px-5 py-4 transition-colors ${
                  e.is_me ? "bg-emerald-50" : "hover:bg-stone-50"
                }`}
              >
                <span
                  className={`w-8 text-center text-lg font-bold tabular-nums ${
                    e.rank <= 3 ? "" : "text-stone-400"
                  }`}
                >
                  {e.rank <= 3 ? MEDALS[e.rank - 1] : e.rank}
                </span>
                <Avatar seed={e.wallet} src={e.avatar_url} size={36} />
                <span className="flex-1 truncate font-medium text-stone-900">
                  {e.display_name}
                  {e.is_me && (
                    <span className="ml-2 rounded-full bg-emerald-200 px-2 py-0.5 text-xs font-semibold text-emerald-900">
                      you
                    </span>
                  )}
                </span>
                <span className="w-20 text-right text-lg font-bold tabular-nums text-emerald-800">
                  {e.points.toLocaleString()}
                </span>
              </li>
            ))}
            {board.entries.length === 0 && (
              <li className="px-5 py-12 text-center text-stone-500">
                No points yet. Be the first tester on the board!
              </li>
            )}
          </ul>
        </Card>
      )}

      {/* Your standing, when you're not already in the visible top 50 */}
      {board && board.my_rank && !onBoard && (
        <Card className="mt-4 flex items-center gap-4 border-emerald-200 bg-emerald-50 px-5 py-4">
          <span className="w-8 text-center font-bold tabular-nums text-stone-500">
            {board.my_rank}
          </span>
          <span className="w-9" aria-hidden />
          <span className="flex-1 font-medium text-stone-900">
            You
            <span className="ml-2 rounded-full bg-emerald-200 px-2 py-0.5 text-xs font-semibold text-emerald-900">
              your rank
            </span>
          </span>
          <span className="w-20 text-right text-lg font-bold tabular-nums text-emerald-800">
            {(board.my_points ?? 0).toLocaleString()}
          </span>
        </Card>
      )}
    </div>
  );
}
