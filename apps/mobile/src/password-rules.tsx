// Password complexity rules + a live checklist, mirroring the web app's
// components/password-rules.tsx (which mirrors the API's app/security.py). Kept
// byte-identical in labels and logic so the native sign-up / reset screens
// validate exactly like the web, and a password accepted here is accepted by
// the API.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Text } from "react-native-paper";
import { emerald, stone } from "@futureroots/tokens";

const RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: "At least 8 characters", test: (p) => p.length >= 8 },
  { label: "An uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "A number", test: (p) => /[0-9]/.test(p) },
  { label: "A symbol (like ! or #)", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

/** True when a password satisfies every complexity rule the API enforces. */
export function passwordMeetsRules(password: string): boolean {
  return RULES.every((r) => r.test(password));
}

/** A live, accessible checklist that ticks each rule green as it is met. */
export function PasswordChecklist({ password }: { password: string }) {
  return (
    <View style={styles.list} accessibilityLiveRegion="polite">
      {RULES.map((rule) => {
        const ok = rule.test(password);
        return (
          <View
            key={rule.label}
            style={styles.row}
            accessibilityRole="text"
            accessibilityLabel={`${rule.label}: ${ok ? "met" : "not met yet"}`}
          >
            <View
              style={[styles.bullet, { backgroundColor: ok ? emerald[100] : stone[100] }]}
            >
              <Text style={[styles.bulletMark, { color: ok ? emerald[700] : stone[400] }]}>
                {ok ? "✓" : "○"}
              </Text>
            </View>
            <Text
              variant="bodySmall"
              style={{ color: ok ? emerald[700] : stone[500] }}
            >
              {rule.label}
            </Text>
          </View>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  list: { marginTop: 8, gap: 6 },
  row: { flexDirection: "row", alignItems: "center", gap: 8 },
  bullet: {
    width: 18,
    height: 18,
    borderRadius: 9,
    alignItems: "center",
    justifyContent: "center",
  },
  bulletMark: { fontSize: 11, fontWeight: "700", lineHeight: 14 },
});
