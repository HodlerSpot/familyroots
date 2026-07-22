// Menu (stub) — profile, notification preferences, premium, and account
// controls arrive in Phase 4. Includes a working sign-out to exercise the
// auth flip end to end.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Button, List, Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/auth-context";

export default function MenuScreen() {
  const { signOut } = useAuth();
  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <View style={styles.content}>
        <Text variant="titleLarge" style={styles.title}>
          Menu
        </Text>
        <List.Section>
          <List.Item title="Profile" left={(p) => <List.Icon {...p} icon="account-circle-outline" />} disabled />
          <List.Item title="Notifications" left={(p) => <List.Icon {...p} icon="bell-outline" />} disabled />
          <List.Item title="FutureRoots Premium" left={(p) => <List.Icon {...p} icon="star-outline" />} disabled />
        </List.Section>
        <Button mode="outlined" onPress={signOut} style={styles.signOut} icon="logout">
          Sign out
        </Button>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { flex: 1, padding: 20, gap: 8 },
  title: { fontWeight: "700" },
  signOut: { marginTop: "auto", borderRadius: 12 },
});
