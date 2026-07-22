// Home (stub). Proves the authed api-client wiring end to end by loading the
// signed-in member via TanStack Query; the real family feed lands in Phase 3.
import React from "react";
import { StyleSheet, View } from "react-native";
import { useQuery } from "@tanstack/react-query";
import { ActivityIndicator, Card, Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { api } from "@/api";

export default function HomeScreen() {
  const { data: me, isLoading } = useQuery({
    queryKey: ["me"],
    queryFn: () => api.me(),
  });

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.content}>
        {isLoading ? (
          <ActivityIndicator />
        ) : (
          <Text variant="headlineSmall" style={styles.greeting}>
            {me ? `Hello, ${me.display_name}` : "Welcome"}
          </Text>
        )}
        <Card mode="outlined" style={styles.card}>
          <Card.Content>
            <Text variant="titleMedium">Your family feed</Text>
            <Text variant="bodyMedium" style={styles.muted}>
              Milestones, memories, and moments will appear here as the app
              comes together.
            </Text>
          </Card.Content>
        </Card>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { flex: 1, padding: 20, gap: 16 },
  greeting: { fontWeight: "700" },
  card: { borderRadius: 16 },
  muted: { opacity: 0.7, marginTop: 6 },
});
