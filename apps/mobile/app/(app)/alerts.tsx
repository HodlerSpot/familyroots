// Alerts (stub) — the in-app notification inbox arrives in Phase 4.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";

export default function AlertsScreen() {
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.content}>
        <Text variant="titleLarge" style={styles.title}>
          Alerts
        </Text>
        <Text variant="bodyMedium" style={styles.muted}>
          Milestone celebrations and family updates will show up here.
        </Text>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { flex: 1, padding: 20, gap: 8 },
  title: { fontWeight: "700" },
  muted: { opacity: 0.7 },
});
