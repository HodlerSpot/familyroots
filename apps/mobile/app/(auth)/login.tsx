// Login screen: a working sign-in that calls api.login(email, password, true)
// via the auth context, stores the always-remembered session, and lets the
// AuthGate route into the app. Copy stays warm and jargon-free.
import React, { useState } from "react";
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from "react-native";
import { Link } from "expo-router";
import { Button, HelperText, Text, TextInput } from "react-native-paper";
import { SafeAreaView } from "react-native-safe-area-context";
import { ApiError } from "@futureroots/api-client";
import { useAuth } from "@/auth-context";

export default function LoginScreen() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const canSubmit = email.trim().length > 0 && password.length > 0 && !busy;

  async function onSubmit() {
    setError(null);
    setBusy(true);
    try {
      await signIn(email.trim(), password);
      // Success: AuthGate redirects into (app).
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setError("That email or password doesn't look right. Please try again.");
      } else {
        setError("We couldn't sign you in just now. Please try again in a moment.");
      }
    } finally {
      setBusy(false);
    }
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
              Welcome back
            </Text>
            <Text variant="bodyLarge" style={styles.subtitle}>
              Sign in to your family.
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
          />
          <TextInput
            label="Password"
            mode="outlined"
            value={password}
            onChangeText={setPassword}
            secureTextEntry={!showPassword}
            autoCapitalize="none"
            autoComplete="password"
            right={
              <TextInput.Icon
                icon={showPassword ? "eye-off" : "eye"}
                onPress={() => setShowPassword((v) => !v)}
              />
            }
            style={styles.input}
            onSubmitEditing={() => canSubmit && onSubmit()}
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
            Sign in
          </Button>

          <View style={styles.footer}>
            <Text variant="bodyMedium">New here? </Text>
            <Link href="/(auth)/signup">
              <Text variant="bodyMedium" style={styles.link}>
                Create an account
              </Text>
            </Link>
          </View>
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
  footer: { flexDirection: "row", justifyContent: "center", marginTop: 20 },
  link: { fontWeight: "700", textDecorationLine: "underline" },
});
