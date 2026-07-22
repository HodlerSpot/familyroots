import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Shared workspace packages ship as TypeScript source; Next transpiles them
  // as part of the web build (they are React-free/DOM-free, consumed here).
  transpilePackages: ["@futureroots/types", "@futureroots/api-client", "@futureroots/tokens"],
};

export default nextConfig;
