// A tiny in-memory hand-off for an invite deep link that arrived while the
// member was signed out.
//
// When someone taps an https://futureroots.app/invites/<token> link (or the
// futureroots:// equivalent) without a session, the root AuthGate would send
// them to the login stack and the token would be lost. So the gate stashes the
// token here first; once sign-in/sign-up flips the app to authed, the gate
// hands it back and routes straight to the invite screen. The JS module scope
// survives the auth flip (same runtime), so no persistence is needed.
let pendingToken: string | null = null;

/** Remember an invite token to complete after authentication. */
export function setPendingInvite(token: string): void {
  pendingToken = token;
}

/** Take (and clear) the pending invite token, if any. */
export function takePendingInvite(): string | null {
  const token = pendingToken;
  pendingToken = null;
  return token;
}
