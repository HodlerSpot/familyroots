// Menu (stub) — profile, notification preferences, premium, and account
// controls arrive in Phase 4. Includes a working sign-out to exercise the
// auth flip end to end, plus the App Lock toggle (Phase 2).
import React from "react";
import { StyleSheet, View } from "react-native";
import { Button, List, Switch, Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/auth-context";
import { useAppLock } from "@/app-lock";

export default function MenuScreen() {
  const { signOut } = useAuth();
  const { capable, enabled, enable, disable } = useAppLock();

  async function onToggleLock(next: boolean) {
    if (next) await enable();
    else await disable();
  }

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
          <List.Item
            title="App Lock"
            description={
              capable
                ? "Use Face ID, Touch ID, or your passcode to open the app"
                : "Set up Face ID, Touch ID, or a passcode on this device to use App Lock"
            }
            left={(p) => <List.Icon {...p} icon="lock-outline" />}
            right={() => (
              <Switch
                value={enabled}
                onValueChange={onToggleLock}
                disabled={!capable}
              />
            )}
          />
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
