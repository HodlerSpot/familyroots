// The gentle monthly Memory Prompt card. Reuses the family memory-prompt
// endpoint and, like the web card, quietly hides itself when there's nothing to
// ask (endpoint returns null), when the member already added a memory this
// month (`satisfied`), or when they dismissed it for this period. The per-month
// dismiss is persisted so the card never nags twice in the same calendar month.
import React, { useEffect, useState } from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import * as SecureStore from "expo-secure-store";
import { Button, Card, IconButton, Text, useTheme } from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";

const DISMISS_KEY = "futureroots.memoryPromptDismissed";

/** Turn "YYYY-MM" into a friendly month name, e.g. "July". */
function monthName(period: string): string {
  const parsed = new Date(`${period}-01T00:00:00`);
  if (Number.isNaN(parsed.getTime())) return "this month's";
  return parsed.toLocaleString("en-US", { month: "long" });
}

export function MemoryPromptCard({ familyId }: { familyId: string }) {
  const router = useRouter();
  const theme = useTheme();
  const [dismissedPeriod, setDismissedPeriod] = useState<string | null>(null);
  const [localDismissed, setLocalDismissed] = useState(false);

  const { data: prompt } = useQuery({
    queryKey: ["memory-prompt", familyId],
    queryFn: () => api.getMemoryPrompt(familyId),
  });

  useEffect(() => {
    let active = true;
    void SecureStore.getItemAsync(DISMISS_KEY)
      .catch(() => null)
      .then((v) => {
        if (active) setDismissedPeriod(v);
      });
    return () => {
      active = false;
    };
  }, []);

  if (!prompt || prompt.satisfied) return null;
  if (localDismissed || dismissedPeriod === prompt.period) return null;

  const { child, period } = prompt;

  function dismiss() {
    setLocalDismissed(true);
    void SecureStore.setItemAsync(DISMISS_KEY, period).catch(() => {});
  }

  return (
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content>
        <View style={styles.headerRow}>
          <Text
            variant="titleMedium"
            style={[styles.title, { color: theme.colors.onPrimaryContainer }]}
          >
            🌱 Add {monthName(period)}'s memory for {child.first_name}
          </Text>
          <IconButton
            icon="close"
            size={18}
            onPress={dismiss}
            accessibilityLabel="Dismiss this reminder"
            style={styles.close}
          />
        </View>
        <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
          A photo, a few words, a little moment: anything you add helps {child.first_name}'s story
          grow. It only takes a minute.
        </Text>
        <Button
          mode="contained"
          style={styles.button}
          onPress={() => router.push(`/child/${child.id}`)}
        >
          Add a memory for {child.first_name}
        </Button>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 16 },
  headerRow: { flexDirection: "row", alignItems: "flex-start", justifyContent: "space-between" },
  title: { flex: 1, fontWeight: "700", paddingRight: 4 },
  close: { margin: 0, marginTop: -6, marginRight: -6 },
  button: { marginTop: 16, borderRadius: 12 },
});
