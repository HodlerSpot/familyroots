// Reset-password screen. Reached by the reset link in the email opening the app
// via either the custom scheme (futureroots://reset-password/<token>) or the
// https Universal Link / App Link (https://futureroots.app/reset-password/<token>);
// expo-router maps that path here from the [token] route param. This lives in
// the (auth) group so an unauthenticated deep-link open is not bounced to login.
// Mirrors apps/web/src/app/reset-password/[token]/page.tsx.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { useLocalSearchParams, useRouter } from "expo-router";
import { Button, HelperText, Text, TextInput } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { PasswordChecklist, passwordMeetsRules } from "@/password-rules";

export default function ResetPasswordScreen() {
  const router = useRouter();
  const { token } = useLocalSearchParams<{ token: string }>();
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  const rulesMet = passwordMeetsRules(password);
  const canSubmit = rulesMet && !busy && typeof token === "string" && token.length > 0;

  async function onSubmit() {
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    try {
      await api.resetPassword(token as string, password);
      setDone(true);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Something went wrong. Please try again."
      );
      setBusy(false);
    }
  }

  if (done) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.confirm}>
          <Text style={styles.emoji}>✅</Text>
          <Text variant="headlineMedium" style={styles.title}>
            Password updated
          </Text>
          <Text variant="bodyLarge" style={styles.confirmBody}>
            You can sign in with your new password now.
          </Text>
          <Button
            mode="contained"
            onPress={() => router.replace("/(auth)/login")}
            style={styles.submit}
            contentStyle={styles.submitContent}
          >
            Sign in
          </Button>
        </View>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
        >
          <View style={styles.header}>
            <Text variant="headlineMedium" style={styles.title}>
              Choose a new password
            </Text>
          </View>

          <TextInput
            label="New password"
            mode="outlined"
            value={password}
            onChangeText={setPassword}
            secureTextEntry={!showPassword}
            autoCapitalize="none"
            autoComplete="password-new"
            textContentType="newPassword"
            right={
              <TextInput.Icon
                icon={showPassword ? "eye-off" : "eye"}
                onPress={() => setShowPassword((v) => !v)}
              />
            }
            style={styles.input}
          />
          <PasswordChecklist password={password} />

          {error ? (
            <HelperText type="error" visible style={styles.error}>
              {error}
            </HelperText>
          ) : null}

          <Button
            mode="contained"
            onPress={onSubmit}
            disabled={!canSubmit}
            loading={busy}
            style={styles.submit}
            contentStyle={styles.submitContent}
          >
            Set new password
          </Button>
        </ScrollView>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1 },
  flex: { flex: 1 },
  content: { padding: 24, gap: 12, flexGrow: 1, justifyContent: "center" },
  header: { marginBottom: 16, gap: 4 },
  title: { fontWeight: "700" },
  input: { marginBottom: 4 },
  error: { marginTop: -4 },
  submit: { marginTop: 12, borderRadius: 12 },
  submitContent: { paddingVertical: 8 },
  confirm: { flex: 1, padding: 24, alignItems: "center", justifyContent: "center", gap: 10 },
  emoji: { fontSize: 44 },
  confirmBody: { textAlign: "center", opacity: 0.8, marginBottom: 8 },
});
