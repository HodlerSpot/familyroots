"use client";

import dynamic from "next/dynamic";

// NEXT_PUBLIC_TESTNET is inlined at build time. In family-product builds this
// is false, the ternary folds away, and the testnet shell (wagmi, react-query,
// wallet gate, quests, banner) is neither mounted nor downloaded: zero UI
// difference. Testnet builds load the shell as its own client-only chunk.
const TestnetShell =
  process.env.NEXT_PUBLIC_TESTNET === "1"
    ? dynamic(() => import("./shell"), { ssr: false })
    : null;

export function TestnetRoot({ children }: { children: React.ReactNode }) {
  if (!TestnetShell) return <>{children}</>;
  return <TestnetShell>{children}</TestnetShell>;
}
