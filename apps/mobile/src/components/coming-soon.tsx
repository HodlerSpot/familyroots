// A warm placeholder for flows that arrive in a later chunk (the write flows —
// add memory, contribute — and the capsules/predictions surfaces). Keeps the
// navigation graph complete so the read screens can link to real routes today,
// without shipping half a feature. No crypto/jargon; gentle, on-brand copy.
import React from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Button, Text, useTheme } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";

export function ComingSoon({
  emoji,
  title,
  body,
}: {
  emoji: string;
  title: string;
  body: string;
}) {
  const router = useRouter();
  const theme = useTheme();
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.content}>
        <Text style={styles.emoji}>{emoji}</Text>
        <Text variant="headlineSmall" style={styles.title}>
          {title}
        </Text>
        <Text variant="bodyLarge" style={[styles.body, { color: theme.colors.onSurfaceVariant }]}>
          {body}
        </Text>
        <Button mode="contained" style={styles.button} onPress={() => router.back()}>
          Go back
        </Button>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { flex: 1, alignItems: "center", justifyContent: "center", padding: 24, gap: 10 },
  emoji: { fontSize: 44, marginBottom: 4 },
  title: { fontWeight: "700", textAlign: "center" },
  body: { textAlign: "center" },
  button: { marginTop: 16, borderRadius: 12 },
});
