// The family switcher sheet, opened from the Home header when a member belongs
// to more than one family. Lists each family with a role chip and a check on
// the active one; picking a family updates the persisted active-family context.
import React from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import { Chip, Divider, List, Modal, Portal, Text, useTheme } from "react-native-paper";
import { useActiveFamily } from "@/active-family";

/** Capitalize a role for display ("grandparent" -> "Grandparent"). */
function roleLabel(role: string): string {
  return role.charAt(0).toUpperCase() + role.slice(1);
}

export function FamilySwitcher({ visible, onDismiss }: { visible: boolean; onDismiss: () => void }) {
  const theme = useTheme();
  const { families, activeFamily, setActiveFamilyId } = useActiveFamily();

  function choose(id: string) {
    setActiveFamilyId(id);
    onDismiss();
  }

  return (
    <Portal>
      <Modal
        visible={visible}
        onDismiss={onDismiss}
        contentContainerStyle={[styles.sheet, { backgroundColor: theme.colors.surface }]}
      >
        <Text variant="titleMedium" style={styles.title}>
          Your families
        </Text>
        <Divider />
        <ScrollView style={styles.list}>
          {families.map((f) => {
            const active = f.id === activeFamily?.id;
            return (
              <List.Item
                key={f.id}
                title={f.name}
                titleStyle={styles.familyName}
                onPress={() => choose(f.id)}
                right={() => (
                  <View style={styles.right}>
                    <Chip compact style={styles.chip} textStyle={styles.chipText}>
                      {roleLabel(f.role)}
                    </Chip>
                    {active ? (
                      <List.Icon icon="check-circle" color={theme.colors.primary} />
                    ) : null}
                  </View>
                )}
              />
            );
          })}
        </ScrollView>
      </Modal>
    </Portal>
  );
}

const styles = StyleSheet.create({
  sheet: { marginHorizontal: 20, borderRadius: 20, paddingVertical: 12, maxHeight: "70%" },
  title: { paddingHorizontal: 20, paddingBottom: 12, fontWeight: "700" },
  list: { paddingHorizontal: 8 },
  familyName: { fontWeight: "600" },
  right: { flexDirection: "row", alignItems: "center", gap: 8 },
  chip: { alignSelf: "center" },
  chipText: { fontSize: 12, textTransform: "capitalize" },
});
