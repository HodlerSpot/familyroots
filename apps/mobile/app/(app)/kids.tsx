// Kids (stub) — each child's vault and future fund arrive in Phase 3.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";

export default function KidsScreen() {
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.content}>
        <Text variant="titleLarge" style={styles.title}>
          Kids
        </Text>
        <Text variant="bodyMedium" style={styles.muted}>
          Each child's vault, milestones, and future fund will live here.
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
