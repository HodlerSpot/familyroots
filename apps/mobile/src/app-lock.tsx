// Biometric app-lock: a UI lock layered over an already-valid session.
//
// This is NOT a second API auth factor — the session token stays valid the
// whole time. It simply hides family content behind Face ID / Touch ID /
// device passcode on cold start and whenever the app returns to the foreground
// after being backgrounded past a short timeout, so a borrowed or lost phone
// does not expose a signed-in family.
//
// Design:
//   - The enabled flag + a "we already offered this" flag live in SecureStore.
//   - Capability is probed once (hasHardware && isEnrolled). If the device can
//     neither do biometrics nor has a passcode enrolled, the feature stays dark
//     and the app is never locked (graceful fallback — you can't be locked out
//     of your own family by a phone that can't authenticate you).
//   - We offer to turn it on exactly once, right after the first sign-in on a
//     device, via a warm dialog. The choice (either way) is remembered.
//   - Locking is only ever enforced while authenticated; the overlay renders
//     above the whole navigator. Sign out is always reachable from the lock
//     screen so a user can never be trapped.
import React, {
  createContext,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AppState, type AppStateStatus, StyleSheet, View } from "react-native";
import * as SecureStore from "expo-secure-store";
import * as LocalAuthentication from "expo-local-authentication";
import { Button, Dialog, Portal, Text, useTheme } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "./auth-context";

const ENABLED_KEY = "futureroots.applock.enabled";
const PROMPT_SEEN_KEY = "futureroots.applock.promptseen";

// Re-lock only after the app has been in the background at least this long, so
// glancing away (a notification, a quick app switch) does not nag on return.
const BACKGROUND_LOCK_TIMEOUT_MS = 3 * 60 * 1000;

const AUTH_PROMPT = "Unlock FutureRoots";

async function probeCapability(): Promise<boolean> {
  try {
    const hasHardware = await LocalAuthentication.hasHardwareAsync();
    const enrolled = await LocalAuthentication.isEnrolledAsync();
    return hasHardware && enrolled;
  } catch {
    return false;
  }
}

/** Run the OS biometric / passcode check. Device-credential fallback stays on,
 * so a device without a fingerprint/face enrolled can still confirm with its
 * passcode. Resolves true only on a successful confirmation. */
async function runAuthentication(): Promise<boolean> {
  try {
    const res = await LocalAuthentication.authenticateAsync({
      promptMessage: AUTH_PROMPT,
      cancelLabel: "Cancel",
      disableDeviceFallback: false,
    });
    return res.success;
  } catch {
    return false;
  }
}

interface AppLockContextValue {
  /** Whether the device can do biometrics/passcode at all. */
  capable: boolean;
  /** Whether the user has turned the lock on. */
  enabled: boolean;
  /** Turn the lock on (confirms with a biometric check first). Returns whether
   * it was enabled. No-op (false) when the device is not capable. */
  enable: () => Promise<boolean>;
  /** Turn the lock off and clear any active lock. */
  disable: () => Promise<void>;
}

const AppLockContext = createContext<AppLockContextValue | null>(null);

export function AppLockProvider({ children }: { children: ReactNode }) {
  const { status, signOut } = useAuth();
  const theme = useTheme();

  const [capable, setCapable] = useState(false);
  const [enabled, setEnabled] = useState(false);
  const [hydrated, setHydrated] = useState(false);
  const [locked, setLocked] = useState(false);
  const [promptVisible, setPromptVisible] = useState(false);
  const [unlocking, setUnlocking] = useState(false);

  const backgroundedAt = useRef<number | null>(null);
  const prevStatus = useRef<typeof status>(status);

  // Boot: probe capability and load the persisted preference. If the lock was
  // left on, start locked so a cold start requires a check before content.
  useEffect(() => {
    let active = true;
    void (async () => {
      const [cap, enabledRaw] = await Promise.all([
        probeCapability(),
        SecureStore.getItemAsync(ENABLED_KEY).catch(() => null),
      ]);
      if (!active) return;
      const on = cap && enabledRaw === "1";
      setCapable(cap);
      setEnabled(on);
      setLocked(on);
      setHydrated(true);
    })();
    return () => {
      active = false;
    };
  }, []);

  // Offer the lock once, right after the first successful sign-in on this
  // device (unauthed -> authed), when the device is capable and we have not
  // asked before. A fresh sign-in also clears any lock (the password just
  // proved identity), so we never wall someone off the moment they log in.
  useEffect(() => {
    if (!hydrated) return;
    // A genuine sign-in is unauthed -> authed. A cold start is loading ->
    // authed: we must NOT unlock there, or the cold-start lock is defeated.
    const isFreshSignIn = prevStatus.current === "unauthed" && status === "authed";
    prevStatus.current = status;
    if (status !== "authed") return;
    if (isFreshSignIn) {
      setLocked(false);
      backgroundedAt.current = null;
      if (capable && !enabled) {
        void SecureStore.getItemAsync(PROMPT_SEEN_KEY)
          .catch(() => null)
          .then((seen) => {
            if (seen !== "1") setPromptVisible(true);
          });
      }
    }
  }, [status, hydrated, capable, enabled]);

  // Re-lock on foreground if we were backgrounded past the timeout.
  useEffect(() => {
    const sub = AppState.addEventListener("change", (next: AppStateStatus) => {
      if (next === "background" || next === "inactive") {
        if (backgroundedAt.current === null) backgroundedAt.current = Date.now();
      } else if (next === "active") {
        const since = backgroundedAt.current;
        backgroundedAt.current = null;
        if (
          enabled &&
          status === "authed" &&
          since !== null &&
          Date.now() - since >= BACKGROUND_LOCK_TIMEOUT_MS
        ) {
          setLocked(true);
        }
      }
    });
    return () => sub.remove();
  }, [enabled, status]);

  async function unlock() {
    if (unlocking) return;
    setUnlocking(true);
    const ok = await runAuthentication();
    setUnlocking(false);
    if (ok) setLocked(false);
  }

  async function persistPromptSeen() {
    await SecureStore.setItemAsync(PROMPT_SEEN_KEY, "1").catch(() => {});
  }

  async function enable(): Promise<boolean> {
    if (!capable) return false;
    const ok = await runAuthentication();
    if (!ok) return false;
    setEnabled(true);
    setLocked(false);
    await SecureStore.setItemAsync(ENABLED_KEY, "1").catch(() => {});
    await persistPromptSeen();
    return true;
  }

  async function disable(): Promise<void> {
    setEnabled(false);
    setLocked(false);
    await SecureStore.setItemAsync(ENABLED_KEY, "0").catch(() => {});
  }

  async function acceptPrompt() {
    setPromptVisible(false);
    await persistPromptSeen();
    await enable();
  }

  async function declinePrompt() {
    setPromptVisible(false);
    await persistPromptSeen();
  }

  const value = useMemo<AppLockContextValue>(
    () => ({ capable, enabled, enable, disable }),
    [capable, enabled]
  );

  const showLock = status === "authed" && enabled && locked;

  return (
    <AppLockContext.Provider value={value}>
      <View style={styles.root}>
        {children}
        {showLock ? (
          <View
            style={[styles.overlay, { backgroundColor: theme.colors.background }]}
          >
            <SafeAreaView style={styles.lockSafe}>
              <View style={styles.lockContent}>
                <Text style={styles.lockEmoji}>🌱</Text>
                <Text variant="headlineSmall" style={styles.lockTitle}>
                  Welcome back
                </Text>
                <Text
                  variant="bodyLarge"
                  style={[styles.lockBody, { color: theme.colors.onSurfaceVariant }]}
                >
                  Unlock to see your family.
                </Text>
                <Button
                  mode="contained"
                  onPress={unlock}
                  loading={unlocking}
                  disabled={unlocking}
                  style={styles.lockButton}
                  contentStyle={styles.lockButtonContent}
                  icon="lock-open-outline"
                >
                  Unlock
                </Button>
                <Button
                  mode="text"
                  onPress={signOut}
                  style={styles.lockSignOut}
                  textColor={theme.colors.onSurfaceVariant}
                >
                  Sign out instead
                </Button>
              </View>
            </SafeAreaView>
          </View>
        ) : null}
      </View>
      <Portal>
        <Dialog visible={promptVisible} dismissable={false}>
          <Dialog.Icon icon="face-recognition" />
          <Dialog.Title style={styles.dialogTitle}>Lock the app?</Dialog.Title>
          <Dialog.Content>
            <Text variant="bodyMedium">
              Add a quick Face ID, Touch ID, or passcode check when you open
              FutureRoots, so your family stays private if your phone is ever out
              of your hands. You can change this anytime in Menu.
            </Text>
          </Dialog.Content>
          <Dialog.Actions>
            <Button onPress={declinePrompt}>Not now</Button>
            <Button onPress={acceptPrompt}>Turn on</Button>
          </Dialog.Actions>
        </Dialog>
      </Portal>
    </AppLockContext.Provider>
  );
}

export function useAppLock(): AppLockContextValue {
  const ctx = useContext(AppLockContext);
  if (!ctx) throw new Error("useAppLock must be used within an AppLockProvider");
  return ctx;
}

const styles = StyleSheet.create({
  root: { flex: 1 },
  overlay: { ...StyleSheet.absoluteFillObject, zIndex: 1000, elevation: 1000 },
  lockSafe: { flex: 1 },
  lockContent: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 8 },
  lockEmoji: { fontSize: 48, marginBottom: 8 },
  lockTitle: { fontWeight: "700" },
  lockBody: { marginBottom: 16, textAlign: "center" },
  lockButton: { borderRadius: 12, minWidth: 220 },
  lockButtonContent: { paddingVertical: 8 },
  lockSignOut: { marginTop: 8 },
  dialogTitle: { textAlign: "center" },
});
