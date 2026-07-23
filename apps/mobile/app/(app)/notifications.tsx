// Notification settings — the native mirror of apps/web/src/app/settings/page.tsx.
//
// Two parts, in one calm scroll:
//   1. This device — native push enrollment (a warm pre-prompt, then the OS
//      permission prompt on tap; a toggle enrolls/unenrolls the Expo push token
//      via the shared api). Denied permission is handled with a link to OS
//      settings, never a dead end.
//   2. What we let you know about — the same 22-boolean email/push matrix as the
//      web app, using the identical pref keys, descriptions, and grouping
//      (docs/brand/notifications-copy.md). The dense two-column web grid is
//      re-laid-out for a narrow screen: one grouped card per topic, each row a
//      description with an Email and a Push switch beneath it, generously spaced.
import React, { useCallback, useEffect, useState } from "react";
import { Linking, ScrollView, StyleSheet, View } from "react-native";
import {
  ActivityIndicator,
  Button,
  Card,
  Divider,
  HelperText,
  Switch,
  Text,
  useTheme,
} from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import type { NotificationPrefs, NotificationSettings } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import {
  disablePush,
  enablePush,
  getPushPermission,
  isEnrolled,
  type PushPermission,
} from "@/push";

type PrefKey = keyof NotificationPrefs;

// Copy verbatim from the web settings page (docs/brand/notifications-copy.md).
const GROUPS: {
  heading: string;
  rows: { emailKey: PrefKey; pushKey: PrefKey; description: string }[];
}[] = [
  {
    heading: "Family moments",
    rows: [
      {
        emailKey: "email_new_member",
        pushKey: "push_new_member",
        description: "When someone joins your family on FutureRoots.",
      },
      {
        emailKey: "email_milestone",
        pushKey: "push_milestone",
        description: "When a child reaches a milestone worth celebrating.",
      },
      {
        emailKey: "email_memory",
        pushKey: "push_memory",
        description: "When a new photo, video, or memory is added to the vault.",
      },
      {
        emailKey: "email_legacy",
        pushKey: "push_legacy",
        description: "When a new story or piece of wisdom joins your family's archive.",
      },
    ],
  },
  {
    heading: "Reminders",
    rows: [
      {
        emailKey: "email_memory_request",
        pushKey: "push_memory_request",
        description: "A gentle monthly nudge to add a new memory for one of your children.",
      },
    ],
  },
  {
    heading: "Money and funds",
    rows: [
      {
        emailKey: "email_contribution",
        pushKey: "push_contribution",
        description: "When someone gives to a child's Future Fund.",
      },
      {
        emailKey: "email_fund_activated",
        pushKey: "push_fund_activated",
        description: "When a child's Future Fund is ready to receive gifts.",
      },
    ],
  },
  {
    heading: "Time capsules",
    rows: [
      {
        emailKey: "email_capsule_sealed",
        pushKey: "push_capsule_sealed",
        description: "When someone seals a time capsule for a child.",
      },
      {
        emailKey: "email_capsule_released",
        pushKey: "push_capsule_released",
        description: "When a time capsule opens.",
      },
    ],
  },
  {
    heading: "Calls",
    rows: [
      {
        emailKey: "email_call_live",
        pushKey: "push_call_live",
        description: "When a family video call starts.",
      },
    ],
  },
  {
    heading: "From FutureRoots",
    rows: [
      {
        emailKey: "email_announcements",
        pushKey: "push_announcements",
        description: "Occasional news and updates from the FutureRoots team.",
      },
    ],
  },
];

export default function NotificationsScreen() {
  const theme = useTheme();
  const [prefs, setPrefs] = useState<NotificationSettings | null>(null);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let active = true;
    api
      .notificationPrefs()
      .then((p) => active && setPrefs(p))
      .catch(
        (err) =>
          active &&
          setError(err instanceof ApiError ? err.message : "Couldn't load your settings")
      );
    return () => {
      active = false;
    };
  }, []);

  const toggle = useCallback(
    async (key: PrefKey) => {
      if (!prefs) return;
      const previous = prefs;
      const next = { ...prefs, [key]: !prefs[key] };
      setPrefs(next);
      setError("");
      try {
        await api.setNotificationPrefs(next);
        setSaved(true);
        setTimeout(() => setSaved(false), 1800);
      } catch (err) {
        setPrefs(previous); // roll back if it didn't stick
        setError(
          err instanceof ApiError
            ? err.message
            : "We couldn't save that just now. Please try again."
        );
      }
    },
    [prefs]
  );

  if (error && !prefs) {
    return (
      <SafeAreaView style={styles.safe} edges={["bottom"]}>
        <View style={styles.center}>
          <Text style={{ color: theme.colors.error }}>{error}</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!prefs) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={styles.content}>
        <PushCard />

        <View style={styles.savedRow}>
          <Text variant="titleMedium" style={styles.heading}>
            What we let you know about
          </Text>
          {saved ? (
            <Text variant="bodySmall" style={{ color: theme.colors.primary }}>
              Saved
            </Text>
          ) : null}
        </View>

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        {GROUPS.map((group) => (
          <Card key={group.heading} mode="outlined" style={styles.groupCard}>
            <Card.Content style={styles.groupContent}>
              <Text
                variant="labelLarge"
                style={[styles.groupHeading, { color: theme.colors.onSurfaceVariant }]}
              >
                {group.heading.toUpperCase()}
              </Text>
              {group.rows.map((row, i) => (
                <View key={row.emailKey}>
                  {i > 0 ? <Divider style={styles.rowDivider} /> : null}
                  <View style={styles.row}>
                    <Text variant="bodyLarge" style={styles.rowDescription}>
                      {row.description}
                    </Text>
                    <View style={styles.toggles}>
                      <ToggleControl
                        label="Email"
                        value={!!prefs[row.emailKey]}
                        onValueChange={() => toggle(row.emailKey)}
                        a11y={`Email: ${row.description}`}
                      />
                      <ToggleControl
                        label="Push"
                        value={!!prefs[row.pushKey]}
                        onValueChange={() => toggle(row.pushKey)}
                        a11y={`Push: ${row.description}`}
                      />
                    </View>
                  </View>
                </View>
              ))}
            </Card.Content>
          </Card>
        ))}

        <Text
          variant="bodySmall"
          style={[styles.footnote, { color: theme.colors.onSurfaceVariant }]}
        >
          No matter what's on or off above, you'll always find everything waiting for you in the
          app.
        </Text>
      </ScrollView>
    </SafeAreaView>
  );
}

function ToggleControl({
  label,
  value,
  onValueChange,
  a11y,
}: {
  label: string;
  value: boolean;
  onValueChange: () => void;
  a11y: string;
}) {
  const theme = useTheme();
  return (
    <View style={styles.toggle}>
      <Text variant="labelMedium" style={{ color: theme.colors.onSurfaceVariant }}>
        {label}
      </Text>
      <Switch value={value} onValueChange={onValueChange} accessibilityLabel={a11y} />
    </View>
  );
}

/** "This device" native-push enrollment card. Its own little state machine:
 * loading -> (granted+enrolled) on / (undetermined|granted-not-enrolled) ready /
 * denied blocked / unavailable (no project credentials yet). */
function PushCard() {
  const theme = useTheme();
  const [permission, setPermission] = useState<PushPermission | null>(null);
  const [enrolled, setEnrolled] = useState(false);
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const refresh = useCallback(async () => {
    const [perm, on] = await Promise.all([getPushPermission(), isEnrolled()]);
    setPermission(perm);
    setEnrolled(on && perm === "granted");
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function onEnable() {
    setBusy(true);
    setNote("");
    const result = await enablePush();
    if (result.ok) {
      setEnrolled(true);
      setPermission("granted");
    } else if (result.reason === "denied") {
      setPermission("denied");
    } else {
      setNote(
        "We couldn't turn on notifications on this device just now. Please try again a little later."
      );
    }
    setBusy(false);
  }

  async function onDisable() {
    setBusy(true);
    setNote("");
    await disablePush();
    setEnrolled(false);
    setBusy(false);
  }

  return (
    <Card mode="contained" style={[styles.pushCard, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content style={styles.pushContent}>
        <Text variant="titleMedium" style={[styles.pushTitle, { color: theme.colors.onPrimaryContainer }]}>
          Notifications on this device
        </Text>

        {permission === null ? (
          <ActivityIndicator style={styles.pushLoading} />
        ) : enrolled ? (
          <>
            <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
              You're all set. This device will get a gentle heads-up the moment something happens
              in your family.
            </Text>
            <Button mode="text" onPress={onDisable} loading={busy} disabled={busy}>
              Turn off on this device
            </Button>
          </>
        ) : permission === "denied" ? (
          <>
            <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
              Notifications are turned off for FutureRoots in your device settings. You can turn
              them back on there whenever you like.
            </Text>
            <Button mode="contained-tonal" icon="cog-outline" onPress={() => void Linking.openSettings()}>
              Open settings
            </Button>
          </>
        ) : (
          <>
            <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
              Get a gentle heads-up on this device the moment something happens in your family, a
              new memory, a milestone, a gift, or a family call.
            </Text>
            <Button
              mode="contained"
              icon="bell-ring-outline"
              onPress={onEnable}
              loading={busy}
              disabled={busy}
              style={styles.pushButton}
            >
              Turn on notifications
            </Button>
          </>
        )}

        {note ? (
          <HelperText type="error" visible>
            {note}
          </HelperText>
        ) : null}
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24 },
  content: { padding: 16, gap: 16 },
  pushCard: { borderRadius: 16 },
  pushContent: { gap: 10 },
  pushTitle: { fontWeight: "700" },
  pushLoading: { alignSelf: "flex-start" },
  pushButton: { borderRadius: 12, alignSelf: "flex-start", marginTop: 2 },
  savedRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  heading: { fontWeight: "700" },
  groupCard: { borderRadius: 16 },
  groupContent: { gap: 4, paddingVertical: 8 },
  groupHeading: { letterSpacing: 0.5, marginBottom: 4 },
  rowDivider: { marginVertical: 4 },
  row: { paddingVertical: 8, gap: 10 },
  rowDescription: {},
  toggles: { flexDirection: "row", gap: 28 },
  toggle: { flexDirection: "row", alignItems: "center", gap: 8 },
  footnote: { textAlign: "center", marginTop: 4, marginBottom: 8 },
});
