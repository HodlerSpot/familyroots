// The pre-join "Who's here?" sheet. Shown right after Start/Join when the family
// has children, so the grownup can tap which little ones are in the room with
// them (this drives the presence chips everyone sees). Kept to one tap: pick
// faces, then join. Skippable with "Just me for now". Mirrors the web
// WhoIsHereModal.
import React, { useEffect, useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { Button, Modal, Portal, Text, TouchableRipple, useTheme } from "react-native-paper";
import { MaterialCommunityIcons } from "@expo/vector-icons";
import type { ChildOut } from "@futureroots/types";
import { Avatar } from "@/components/avatar";

export function WhoIsHereSheet({
  visible,
  children,
  busy,
  onConfirm,
  onDismiss,
}: {
  visible: boolean;
  children: ChildOut[];
  busy: boolean;
  /** childIds of the little ones present (empty = just me). */
  onConfirm: (childIds: string[]) => void;
  onDismiss: () => void;
}) {
  const theme = useTheme();
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // Start fresh each time the picker opens.
  useEffect(() => {
    if (visible) setSelected(new Set());
  }, [visible]);

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const count = selected.size;
  const joinLabel = busy
    ? "Joining..."
    : count === 0
      ? "Join the call"
      : count === 1
        ? "Join the call with 1 little one"
        : `Join the call with ${count} little ones`;

  return (
    <Portal>
      <Modal
        visible={visible}
        onDismiss={busy ? undefined : onDismiss}
        contentContainerStyle={[styles.sheet, { backgroundColor: theme.colors.surface }]}
      >
        <Text variant="titleLarge" style={styles.title}>
          Who's here with you?
        </Text>
        <Text variant="bodyMedium" style={[styles.sub, { color: theme.colors.onSurfaceVariant }]}>
          Tap everyone who is in the room with you, so the rest of the family knows who they'll see.
        </Text>

        <ScrollView contentContainerStyle={styles.grid} style={styles.gridScroll}>
          {children.map((c) => {
            const on = selected.has(c.id);
            return (
              <TouchableRipple
                key={c.id}
                onPress={() => toggle(c.id)}
                borderless
                style={[
                  styles.child,
                  {
                    borderColor: on ? theme.colors.primary : theme.colors.outlineVariant,
                    backgroundColor: on ? theme.colors.primaryContainer : theme.colors.surface,
                  },
                ]}
                accessibilityRole="checkbox"
                accessibilityState={{ checked: on }}
                accessibilityLabel={`${c.first_name}${on ? ", here" : ", not here"}`}
              >
                <View style={styles.childInner}>
                  <View>
                    <Avatar name={c.first_name} mediaId={c.avatar_media_id} size={64} />
                    {on ? (
                      <View style={[styles.check, { backgroundColor: theme.colors.primary }]}>
                        <MaterialCommunityIcons name="check" size={16} color="#ffffff" />
                      </View>
                    ) : null}
                  </View>
                  <Text variant="bodyMedium" style={styles.childName} numberOfLines={1}>
                    {c.first_name}
                  </Text>
                </View>
              </TouchableRipple>
            );
          })}
        </ScrollView>

        <View style={styles.actions}>
          <Button
            mode="contained"
            onPress={() => onConfirm(Array.from(selected))}
            loading={busy}
            disabled={busy}
            contentStyle={styles.actionContent}
          >
            {joinLabel}
          </Button>
          <Button mode="text" onPress={() => onConfirm([])} disabled={busy}>
            Just me for now
          </Button>
        </View>
      </Modal>
    </Portal>
  );
}

const styles = StyleSheet.create({
  sheet: { marginHorizontal: 16, borderRadius: 24, padding: 20, maxHeight: "82%" },
  title: { fontWeight: "700" },
  sub: { marginTop: 6, marginBottom: 12 },
  gridScroll: { maxHeight: 320 },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 12, justifyContent: "flex-start" },
  child: {
    width: "30%",
    borderWidth: 2,
    borderRadius: 20,
    padding: 8,
  },
  childInner: { alignItems: "center", gap: 6 },
  check: {
    position: "absolute",
    right: -2,
    bottom: -2,
    width: 24,
    height: 24,
    borderRadius: 12,
    alignItems: "center",
    justifyContent: "center",
  },
  childName: { fontWeight: "600" },
  actions: { marginTop: 16, gap: 8 },
  actionContent: { paddingVertical: 6 },
});
