// Menu — the account/admin surface. Entry points to your profile, notification
// settings, your plan, your families, and your data, plus the biometric App
// Lock toggle (Phase 2) and sign-out.
import React, { useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Button, List, Switch, Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { useAuth } from "@/auth-context";
import { useAppLock } from "@/app-lock";
import { useActiveFamily } from "@/active-family";
import { FamilySwitcher } from "@/components/family-switcher";

export default function MenuScreen() {
  const router = useRouter();
  const { signOut } = useAuth();
  const { capable, enabled, enable, disable } = useAppLock();
  const { activeFamily, families } = useActiveFamily();
  const [switcherOpen, setSwitcherOpen] = useState(false);

  async function onToggleLock(next: boolean) {
    if (next) await enable();
    else await disable();
  }

  const familiesDescription =
    families.length > 1
      ? `${activeFamily?.name ?? "Your families"} and ${families.length - 1} more`
      : activeFamily?.name ?? "The families you belong to";

  return (
    <SafeAreaView style={styles.safe} edges={["bottom"]}>
      <ScrollView contentContainerStyle={styles.content}>
        <List.Section>
          <List.Subheader>Account</List.Subheader>
          <List.Item
            title="Your profile"
            description="Your name, photo, and password"
            left={(p) => <List.Icon {...p} icon="account-circle-outline" />}
            right={(p) => <List.Icon {...p} icon="chevron-right" />}
            onPress={() => router.push("/profile")}
          />
          <List.Item
            title="Notifications"
            description="Choose what we let you know about"
            left={(p) => <List.Icon {...p} icon="bell-outline" />}
            right={(p) => <List.Icon {...p} icon="chevron-right" />}
            onPress={() => router.push("/notifications")}
          />
          <List.Item
            title="FutureRoots Premium"
            description="Your family's plan"
            left={(p) => <List.Icon {...p} icon="star-outline" />}
            right={(p) => <List.Icon {...p} icon="chevron-right" />}
            onPress={() => router.push("/premium")}
          />
          <List.Item
            title="Your families"
            description={familiesDescription}
            left={(p) => <List.Icon {...p} icon="account-group-outline" />}
            right={(p) => <List.Icon {...p} icon="chevron-right" />}
            onPress={() => setSwitcherOpen(true)}
          />
          <List.Item
            title="Your data"
            description="Download a copy, or close your account"
            left={(p) => <List.Icon {...p} icon="shield-account-outline" />}
            right={(p) => <List.Icon {...p} icon="chevron-right" />}
            onPress={() => router.push("/your-data")}
          />
        </List.Section>

        <List.Section>
          <List.Subheader>This device</List.Subheader>
          <List.Item
            title="App Lock"
            description={
              capable
                ? "Use Face ID, Touch ID, or your passcode to open the app"
                : "Set up Face ID, Touch ID, or a passcode on this device to use App Lock"
            }
            left={(p) => <List.Icon {...p} icon="lock-outline" />}
            right={() => <Switch value={enabled} onValueChange={onToggleLock} disabled={!capable} />}
          />
        </List.Section>

        <View style={styles.footer}>
          <Button mode="outlined" onPress={signOut} style={styles.signOut} icon="logout">
            Sign out
          </Button>
        </View>
      </ScrollView>

      <FamilySwitcher visible={switcherOpen} onDismiss={() => setSwitcherOpen(false)} />
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { paddingVertical: 8, paddingBottom: 24 },
  footer: { padding: 20 },
  signOut: { borderRadius: 12 },
});
