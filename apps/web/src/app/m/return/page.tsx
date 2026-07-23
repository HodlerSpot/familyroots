"use client";

/**
 * Mobile deep-link return bridge.
 *
 * Hosted Stripe/Connect flows (Premium Checkout, Premium gift, the Billing
 * Portal, Future Fund onboarding) launched from the native app run in an in-app
 * browser and can only redirect to an https URL. The API points those return
 * URLs here (see apps/api/app/return_urls.py) with a `to` target; this page
 * immediately hands control back to the app via the futureroots:// scheme and
 * shows a warm fallback if the app doesn't open on its own.
 *
 * The `to` target vocabulary is a contract shared with the API:
 *   premium-success | premium-cancel | gift-success | gift-cancel |
 *   portal | fund-return | fund-refresh
 *
 * No secrets, no API calls — just a redirect + a friendly note.
 */

import { Suspense, useEffect, useMemo } from "react";
import { useSearchParams } from "next/navigation";

const APP_SCHEME = "futureroots://";

/** Map a `to` target + params to the shared app/web route path (no leading slash). */
function routePath(to: string | null, params: URLSearchParams): string {
  const familyId = params.get("family_id") ?? "";
  const childId = params.get("child_id") ?? "";
  switch (to) {
    case "premium-success":
      return `family/${familyId}/premium/success`;
    case "premium-cancel":
      return `family/${familyId}/premium`;
    case "gift-success":
      return `family/${familyId}/premium/gift/success`;
    case "gift-cancel":
      return `family/${familyId}/premium/gift`;
    case "portal":
      return `family/${familyId}`;
    case "fund-return":
      return `family/${familyId}/child/${childId}/fund/setup/return`;
    case "fund-refresh":
      return `family/${familyId}/child/${childId}/fund/setup/refresh`;
    default:
      return "";
  }
}

export default function MobileReturnPage() {
  return (
    <Suspense fallback={<p className="text-stone-500">One moment…</p>}>
      <ReturnInner />
    </Suspense>
  );
}

function ReturnInner() {
  const params = useSearchParams();
  const to = params.get("to");

  const { deepLink, webHref } = useMemo(() => {
    const path = routePath(to, params);
    // Stripe adds session_id on success returns; carry it through to the app.
    const sessionId = params.get("session_id");
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    return {
      deepLink: `${APP_SCHEME}${path}${query}`,
      webHref: `/${path}${query}`,
    };
  }, [to, params]);

  // Hand control straight back to the app. If the app is installed this opens
  // it; otherwise nothing happens and the fallback below stays on screen.
  useEffect(() => {
    window.location.href = deepLink;
  }, [deepLink]);

  return (
    <div className="mx-auto max-w-lg">
      <div className="rounded-2xl border border-stone-200 bg-white p-8 text-center shadow-sm">
        <div aria-hidden className="text-5xl">
          🌿
        </div>
        <h1 className="mt-3 text-2xl font-bold text-emerald-900">All set</h1>
        <p className="mt-2 text-stone-600">
          You can return to the FutureRoots app now. If it didn&apos;t reopen on its own, tap
          below.
        </p>
        <a
          href={deepLink}
          className="mt-6 inline-block rounded-lg bg-emerald-700 px-5 py-3 text-base font-semibold text-white transition-colors hover:bg-emerald-800"
        >
          Open the app
        </a>
        <p className="mt-6 text-sm text-stone-500">
          Not on the app?{" "}
          <a href={webHref} className="text-emerald-700 underline">
            Continue on futureroots.app
          </a>
        </p>
      </div>
    </div>
  );
}
