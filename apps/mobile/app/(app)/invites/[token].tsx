// Accept a family invitation — the native mirror of the web invite page
// (apps/web/src/app/invites/[token]/page.tsx). Reached by tapping an
// https://futureroots.app/invites/<token> link (Universal / App Link) or the
// futureroots:// equivalent; expo-router maps the [token] param here.
//
// This screen lives in the (app) group, so a signed-in member lands here
// directly. A signed-out tap is caught by the root AuthGate, which stashes the
// token (src/pending-invite.ts), routes through the auth stack, and sends the
// member back here once signed in, so joining "works signed-in or routes
// through auth then accepts" with no lost invitation.
import React, { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import { ActivityIndicator, Button, Text, useTheme } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import type { FamilySummary, InvitePreview } from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { familyPhrase } from "@/format";

export default function AcceptInviteScreen() {
  const theme = useTheme();
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token: string }>();
  const { activateFamily, refetch } = useActiveFamily();

  const [preview, setPreview] = useState<InvitePreview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [joined, setJoined] = useState<FamilySummary | null>(null);

  useEffect(() => {
    let active = true;
    if (!token) {
      setError("We couldn't find this invitation.");
      return;
    }
    api
      .previewInvite(token)
      .then((p) => active && setPreview(p))
      .catch(
        (err) =>
          active &&
          setError(
            err instanceof ApiError && err.status === 410
              ? "This invitation has expired or was already used. Ask your family member to send a new one."
              : "We couldn't find this invitation."
          )
      );
    return () => {
      active = false;
    };
  }, [token]);

  async function join() {
    if (!token) return;
    setBusy(true);
    setError("");
    try {
      const family = await api.acceptInvite(token);
      await queryClient.invalidateQueries({ queryKey: ["families"] });
      refetch();
      activateFamily(family.id);
      setJoined(family);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      setBusy(false);
    }
  }

  if (joined) {
    return (
      <SafeAreaView style={styles.safe}>
        <Stack.Screen options={{ title: "Welcome" }} />
        <View style={styles.center}>
          <Text style={styles.emoji}>🌳</Text>
          <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
            Welcome to {familyPhrase(joined.name, { capitalize: true })}
          </Text>
          <Text variant="bodyLarge" style={[styles.body, { color: theme.colors.onSurfaceVariant }]}>
            You're in. Everything your family shares is waiting for you.
          </Text>
          <Button
            mode="contained"
            style={styles.primary}
            contentStyle={styles.primaryContent}
            onPress={() => router.replace("/(app)/(tabs)")}
          >
            Go to your family
          </Button>
        </View>
      </SafeAreaView>
    );
  }

  if (error && !preview) {
    return (
      <SafeAreaView style={styles.safe}>
        <Stack.Screen options={{ title: "Invitation" }} />
        <View style={styles.center}>
          <Text style={styles.emoji}>💌</Text>
          <Text variant="bodyLarge" style={[styles.body, { color: theme.colors.onSurfaceVariant }]}>
            {error}
          </Text>
          <Button mode="contained-tonal" onPress={() => router.replace("/(app)/(tabs)")}>
            Go home
          </Button>
        </View>
      </SafeAreaView>
    );
  }

  if (!preview) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <Stack.Screen options={{ title: "Invitation" }} />
      <View style={styles.center}>
        <Text style={styles.emoji}>💌</Text>
        <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
          {preview.invited_by} invited you to join{" "}
          {familyPhrase(preview.family_name)}
        </Text>
        <Text variant="bodyLarge" style={[styles.body, { color: theme.colors.onSurfaceVariant }]}>
          You're joining as a {preview.role} in a private space where your family shares memories,
          celebrates milestones, and builds a future together.
        </Text>
        {error ? (
          <Text variant="bodyMedium" style={{ color: theme.colors.error, textAlign: "center" }}>
            {error}
          </Text>
        ) : null}
        <Button
          mode="contained"
          onPress={join}
          loading={busy}
          disabled={busy}
          style={styles.primary}
          contentStyle={styles.primaryContent}
        >
          Join your family
        </Button>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 14 },
  emoji: { fontSize: 52 },
  title: { fontWeight: "700", textAlign: "center" },
  body: { textAlign: "center" },
  primary: { borderRadius: 12, alignSelf: "stretch", marginTop: 6 },
  primaryContent: { paddingVertical: 8 },
});
