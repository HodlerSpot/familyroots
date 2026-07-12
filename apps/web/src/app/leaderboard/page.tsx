"use client";

// Tester leaderboard. Only reachable on the testnet build; on the family
// product this route renders nothing meaningful (the API endpoint 404s).
// Polls every 5 seconds so ranks shift in near real time.

import { useCallback, useEffect, useState } from "react";
import { Leaderboard, testnetApi } from "@/components/testnet/api";
import { Card } from "@/components/ui";

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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-emerald-900">Tester leaderboard 🏆</h1>
          <p className="text-stone-600">
            Every action you test earns points. Thank you for helping families keep their
            memories safe.
          </p>
        </div>
        <a href="/family" className="text-sm text-stone-500 underline">
          Back to testing
        </a>
      </div>

      {error && <Card>{error}</Card>}

      {board && (
        <Card className="overflow-hidden p-0">
          <ul className="divide-y divide-stone-100">
            {board.entries.map((e) => (
              <li
                key={e.rank}
                className={`flex items-center gap-4 px-5 py-3 ${
                  e.is_me ? "bg-emerald-50" : ""
                }`}
              >
                <span
                  className={`w-8 text-center text-lg font-bold tabular-nums ${
                    e.rank <= 3 ? "text-emerald-700" : "text-stone-400"
                  }`}
                >
                  {e.rank <= 3 ? ["🥇", "🥈", "🥉"][e.rank - 1] : e.rank}
                </span>
                <span className="flex-1 font-medium text-stone-900">
                  {e.display_name}
                  {e.is_me && (
                    <span className="ml-2 rounded-full bg-emerald-200 px-2 py-0.5 text-xs text-emerald-900">
                      you
                    </span>
                  )}
                </span>
                <span className="font-bold tabular-nums text-emerald-800">{e.points}</span>
              </li>
            ))}
            {board.entries.length === 0 && (
              <li className="px-5 py-8 text-center text-stone-500">
                No points yet. Be the first tester on the board!
              </li>
            )}
          </ul>
        </Card>
      )}

      {board && board.my_rank && !board.entries.some((e) => e.is_me) && (
        <Card className="flex items-center gap-4 bg-emerald-50">
          <span className="w-8 text-center font-bold tabular-nums text-stone-400">
            {board.my_rank}
          </span>
          <span className="flex-1 font-medium text-stone-900">You</span>
          <span className="font-bold tabular-nums text-emerald-800">{board.my_points}</span>
        </Card>
      )}
    </div>
  );
}
