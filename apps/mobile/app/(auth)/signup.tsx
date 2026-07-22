// Sign-up stub. The full create-account flow (with parental-consent framing)
// lands in Phase 2; for now this points members back to sign-in.
import React from "react";
import { StyleSheet, View } from "react-native";
import { useRouter } from "expo-router";
import { Button, Text } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";

export default function SignupScreen() {
  const router = useRouter();
  return (
    <SafeAreaView style={styles.safe}>
      <View style={styles.content}>
        <Text variant="headlineMedium" style={styles.title}>
          Create your account
        </Text>
        <Text variant="bodyLarge" style={styles.body}>
          Getting started is coming soon to the app. For now, please sign in
          with an account you already have.
        </Text>
        <Button mode="contained" onPress={() => router.replace("/(auth)/login")} style={styles.button}>
          Back to sign in
        </Button>
      </View>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  content: { flex: 1, padding: 24, justifyContent: "center", gap: 16 },
  title: { fontWeight: "700" },
  body: { opacity: 0.75 },
  button: { marginTop: 8, borderRadius: 12 },
});
