// Opening a Stripe-hosted flow (Premium checkout, gift checkout, billing
// portal) from native.
//
// The backend, told which platform we are on via the X-Client-Platform header
// (wired in src/api.ts), returns URLs whose success/cancel redirects bounce
// through a small https bridge on futureroots.app that then invokes the
// futureroots:// scheme. We open the hosted page in a secure in-app browser
// (ASWebAuthenticationSession on iOS / Custom Tab on Android) with
// openAuthSessionAsync, giving it the futureroots:// return scheme so the sheet
// closes itself the moment the bridge bounces back — no manual dismissal, no
// leaked cookies. The caller always refetches entitlement/plan on return, since
// Stripe settles the real state via webhook a moment later either way.
import * as WebBrowser from "expo-web-browser";

// Any futureroots:// URL closes the auth session; the bridge picks the path.
// openAuthSessionAsync keys off the scheme, so this exact path need not match.
const RETURN_URL = "futureroots://premium-return";

export type HostedFlowResult = "returned" | "dismissed";

/** Open a Stripe-hosted URL in the in-app browser and resolve once the member
 * returns (either via the futureroots:// bridge redirect or by closing it). */
export async function openHostedFlow(url: string): Promise<HostedFlowResult> {
  try {
    const result = await WebBrowser.openAuthSessionAsync(url, RETURN_URL);
    // "success" = the bridge redirected back to our scheme; "cancel"/"dismiss"
    // = the member closed the sheet. We refetch on both, so the distinction is
    // only for whether to show a gentle "no changes" note.
    return result.type === "success" ? "returned" : "dismissed";
  } catch {
    // A failure to open the browser (rare) is treated as a dismissal; the
    // caller's refetch keeps the UI honest.
    return "dismissed";
  }
}
