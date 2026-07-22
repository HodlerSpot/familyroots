// Forgot-password screen: email in, then the same warm "check your email"
// confirmation the web shows. The API never reveals whether an account exists,
// so the confirmation is phrased "if an account exists" to avoid leaking that.
// Mirrors apps/web/src/app/forgot-password/page.tsx.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { Link, useRouter } from "expo-router";
import { Button, HelperText, Text, TextInput } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";

export default function ForgotPasswordScreen() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canSubmit = email.trim().length > 0 && !busy;

  async function onSubmit() {
    if (!canSubmit) return;
    setError(null);
    setBusy(true);
    try {
      await api.forgotPassword(email.trim());
      setSent(true);
    } catch (e) {
      setError(
        e instanceof ApiError ? e.message : "Something went wrong. Please try again."
      );
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.confirm}>
          <Text style={styles.emoji}>📬</Text>
          <Text variant="headlineMedium" style={styles.title}>
            Check your email
          </Text>
          <Text variant="bodyLarge" style={styles.confirmBody}>
            If an account exists for {email.trim()}, a reset link is on its way. It
            works once and expires in an hour.
          </Text>
          <Text variant="bodyMedium" style={styles.hint}>
            Nothing arriving? Check your spam folder, or try again.
          </Text>
          <Button
            mode="text"
            onPress={() => {
              setSent(false);
              setError(null);
            }}
            style={styles.retry}
          >
            Try a different email
          </Button>
          <Button mode="contained" onPress={() => router.replace("/(auth)/login")} style={styles.submit} contentStyle={styles.submitContent}>
            Back to sign in
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
              Reset your password
            </Text>
            <Text variant="bodyLarge" style={styles.subtitle}>
              Enter your email and we'll send you a link to choose a new one.
            </Text>
          </View>

          <TextInput
            label="Email"
            mode="outlined"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoComplete="email"
            keyboardType="email-address"
            inputMode="email"
            style={styles.input}
            onSubmitEditing={onSubmit}
          />

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
            Send reset link
          </Button>

          <Link href="/(auth)/login" style={styles.back}>
            <Text variant="bodyMedium" style={styles.backText}>
              Back to sign in
            </Text>
          </Link>
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
  subtitle: { opacity: 0.7 },
  input: { marginBottom: 4 },
  error: { marginTop: -4 },
  submit: { marginTop: 12, borderRadius: 12 },
  submitContent: { paddingVertical: 8 },
  back: { alignSelf: "center", marginTop: 20 },
  backText: { textDecorationLine: "underline", opacity: 0.7 },
  confirm: { flex: 1, padding: 24, alignItems: "center", justifyContent: "center", gap: 10 },
  emoji: { fontSize: 44 },
  confirmBody: { textAlign: "center", opacity: 0.8 },
  hint: { textAlign: "center", opacity: 0.6, marginTop: 4 },
  retry: { marginTop: 4 },
});
