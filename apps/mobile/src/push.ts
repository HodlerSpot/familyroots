// Native push enrollment for this device.
//
// Web push uses VAPID + a service worker (settings/page.tsx); native has none
// of that. Instead we ask the OS for permission, acquire an Expo push token,
// and register it with the API via the shared client (POST /me/native-push-
// tokens). The backend fans notifications out through the Expo Push API, gated
// by the very same 22-boolean preference matrix as email/web push. Disabling
// unregisters the token so this device stops receiving pushes.
//
// The permission prompt only ever fires from an explicit "Turn on" tap, after
// a warm pre-prompt in the UI — never on cold start.
import { Platform } from "react-native";
import Constants from "expo-constants";
import * as SecureStore from "expo-secure-store";
import * as Notifications from "expo-notifications";
import { api } from "./api";

const TOKEN_KEY = "futureroots.expoPushToken";

// Foreground notifications should still show a banner + play a sound (families
// want the milestone alert even with the app open).
Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowBanner: true,
    shouldShowList: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
  }),
});

export type PushPermission = "granted" | "denied" | "undetermined";

/** The platform value the API expects; native is always ios or android. */
function platformTag(): "ios" | "android" {
  return Platform.OS === "android" ? "android" : "ios";
}

/** A friendly label for this device, shown if we ever list enrolled devices. */
function deviceLabel(): string | undefined {
  return Constants.deviceName ?? undefined;
}

/** The EAS project id the Expo push service needs to mint a token. Empty until
 * the founder provisions the EAS project (see app.config.ts extra.eas). */
function projectId(): string | undefined {
  const id =
    (Constants.expoConfig?.extra?.eas as { projectId?: string } | undefined)?.projectId ??
    (Constants as unknown as { easConfig?: { projectId?: string } }).easConfig?.projectId;
  return id && id.length > 0 ? id : undefined;
}

/** Current OS-level permission for notifications (does not prompt). */
export async function getPushPermission(): Promise<PushPermission> {
  const { status } = await Notifications.getPermissionsAsync();
  if (status === "granted") return "granted";
  if (status === "denied") return "denied";
  return "undetermined";
}

/** True when this device already holds a registered Expo push token. */
export async function isEnrolled(): Promise<boolean> {
  try {
    return (await SecureStore.getItemAsync(TOKEN_KEY)) !== null;
  } catch {
    return false;
  }
}

export type EnableResult =
  | { ok: true }
  | { ok: false; reason: "denied" | "unavailable" };

/** Request permission (if needed), acquire the Expo push token, and register
 * it with the API. Safe to call again; re-registration just refreshes it. */
export async function enablePush(): Promise<EnableResult> {
  const existing = await Notifications.getPermissionsAsync();
  let status = existing.status;
  if (status !== "granted") {
    // The single, intentional permission prompt.
    const requested = await Notifications.requestPermissionsAsync();
    status = requested.status;
  }
  if (status !== "granted") {
    return { ok: false, reason: "denied" };
  }
  try {
    const pid = projectId();
    const { data: token } = await Notifications.getExpoPushTokenAsync(
      pid ? { projectId: pid } : undefined
    );
    await api.registerNativePush(token, platformTag(), deviceLabel());
    await SecureStore.setItemAsync(TOKEN_KEY, token).catch(() => {});
    return { ok: true };
  } catch {
    // No projectId yet, or the Expo push service was unreachable.
    return { ok: false, reason: "unavailable" };
  }
}

/** Unregister this device's token with the API and forget it locally. */
export async function disablePush(): Promise<void> {
  let token: string | null = null;
  try {
    token = await SecureStore.getItemAsync(TOKEN_KEY);
  } catch {
    token = null;
  }
  if (token) {
    try {
      await api.unregisterNativePush(token);
    } catch {
      // The backend prunes dead tokens on its next send anyway.
    }
  }
  await SecureStore.deleteItemAsync(TOKEN_KEY).catch(() => {});
}
