# Next.js version note

This app runs **Next.js 15** (App Router) — deliberately not 16, because AWS Amplify Hosting's SSR compute supports Next.js only through 15. Do not upgrade to 16 until Amplify announces support.

Patterns in use: client components with `useParams()`/`useSearchParams()` (the latter wrapped in `<Suspense>`), Tailwind v4 via `@tailwindcss/postcss`, `metadata` export only in the server `layout.tsx`. Dynamic-route `params` props are Promises in server components — but all dynamic pages here are client components using `useParams()`, which stays synchronous.
