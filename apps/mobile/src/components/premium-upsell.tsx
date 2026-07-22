// The warm FutureRoots Premium upsell, shown inline when a member reaches a
// gated capability (today: recording or picking a video on a Free family).
//
// It is an invitation, never a wall: the copy is lifted verbatim from the web
// upsell (apps/web/src/components/premium/PremiumUpsell.tsx, sourced from
// docs/brand/premium-copy.md) so both surfaces speak with one voice. The
// Upgrade / Gift call to action opens the Premium manage/gift screens, which
// land in Phase 4; until then this offers a gentle "Maybe later" that returns
// the member to the other (free) ways to add a memory.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Button, Card, Text, useTheme } from "react-native-paper";
import type { FamilyRole } from "@futureroots/types";

const CAPABILITY_COPY: Record<string, { title: string; body: string }> = {
  video_upload: {
    title: "Videos are part of FutureRoots Premium",
    body: "Photos and voice notes are always free. Premium adds video memories and family video calls for the whole family, $9.99 a month or $99 a year.",
  },
  family_video_call: {
    title: "Family video calls are part of Premium",
    body: "See everyone's faces, from anywhere. One membership covers the whole family, $9.99 a month or $99 a year.",
  },
};

const DEFAULT_COPY = {
  title: "This is part of FutureRoots Premium.",
  body: "More room for your family's story. One membership covers everyone.",
};

const NON_PARENT_HELPER = "Or mention it to a parent. Upgrading takes about a minute.";

export function PremiumUpsellCard({
  capability,
  role,
  onDismiss,
}: {
  capability: string;
  role: FamilyRole | null;
  onDismiss: () => void;
}) {
  const theme = useTheme();
  const copy = CAPABILITY_COPY[capability] ?? DEFAULT_COPY;
  const isParent = role === "parent";

  return (
    <Card
      mode="contained"
      style={[styles.card, { backgroundColor: theme.colors.secondaryContainer }]}
    >
      <Card.Content style={styles.content}>
        <View style={styles.headRow}>
          <Text style={styles.spark} accessibilityElementsHidden>
            ✨
          </Text>
          <View style={styles.headText}>
            <Text
              variant="titleMedium"
              style={[styles.title, { color: theme.colors.onSecondaryContainer }]}
            >
              {copy.title}
            </Text>
            <Text
              variant="bodyMedium"
              style={{ color: theme.colors.onSecondaryContainer }}
            >
              {copy.body}
            </Text>
            {!isParent ? (
              <Text
                variant="bodySmall"
                style={[styles.helper, { color: theme.colors.onSurfaceVariant }]}
              >
                {NON_PARENT_HELPER}
              </Text>
            ) : null}
          </View>
        </View>
        <Button mode="text" onPress={onDismiss} style={styles.dismiss}>
          Maybe later
        </Button>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  card: { borderRadius: 16 },
  content: { gap: 8 },
  headRow: { flexDirection: "row", gap: 12 },
  spark: { fontSize: 24, lineHeight: 30 },
  headText: { flex: 1, minWidth: 0, gap: 4 },
  title: { fontWeight: "700" },
  helper: { marginTop: 2 },
  dismiss: { alignSelf: "flex-start" },
});
