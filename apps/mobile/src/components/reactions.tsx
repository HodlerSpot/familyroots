// The warm row of emoji reaction pills shown under a moment or a comment. Tap
// a pill to toggle your reaction; the count and highlighted state come straight
// from the server's ReactionSummary. Mirrors the web feed's ReactionBar, with
// touch targets sized for grandparent-grade tapping.
import React from "react";
import { Pressable, StyleSheet, View } from "react-native";
import { Text, useTheme } from "react-native-paper";
import { REACTION_EMOJI, type ReactionSummary } from "@futureroots/types";

export function ReactionBar({
  reactions,
  onToggle,
  size = "md",
}: {
  reactions: ReactionSummary[];
  onToggle: (emoji: string) => void;
  size?: "md" | "sm";
}) {
  const theme = useTheme();
  const byEmoji = new Map(reactions.map((r) => [r.emoji, r]));
  const minHeight = size === "sm" ? 34 : 40;
  const fontSize = size === "sm" ? 14 : 16;

  return (
    <View style={styles.row}>
      {REACTION_EMOJI.map((emoji) => {
        const summary = byEmoji.get(emoji);
        const count = summary?.count ?? 0;
        const reacted = summary?.reacted ?? false;
        return (
          <Pressable
            key={emoji}
            onPress={() => onToggle(emoji)}
            accessibilityRole="button"
            accessibilityState={{ selected: reacted }}
            accessibilityLabel={`React ${emoji}${count > 0 ? `, ${count}` : ""}`}
            style={[
              styles.pill,
              { minHeight, borderColor: theme.colors.outlineVariant },
              reacted && {
                backgroundColor: theme.colors.primaryContainer,
                borderColor: theme.colors.primary,
              },
            ]}
          >
            <Text style={{ fontSize }}>{emoji}</Text>
            {count > 0 && (
              <Text
                style={[
                  styles.count,
                  { fontSize: fontSize - 2, color: theme.colors.onSurface },
                ]}
              >
                {count}
              </Text>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "row", flexWrap: "wrap", gap: 8, alignItems: "center" },
  pill: {
    flexDirection: "row",
    alignItems: "center",
    gap: 4,
    borderWidth: 1,
    borderRadius: 999,
    paddingHorizontal: 12,
  },
  count: { fontWeight: "600", fontVariant: ["tabular-nums"] },
});
