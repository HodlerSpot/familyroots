// The "Set the next call" sheet, opened from the call card. Grandparent-first
// scheduling: instead of a fiddly date-time wheel, pick a day and a time from
// warm presets, add an optional note, and save. Mirrors the web PlannedCallModal
// (day + time + note -> setPlannedCall) but tuned for one-tap-per-choice on a
// phone. Premium-gated: a 402 backstop hands off to the upsell, never an error.
import React, { useEffect, useMemo, useState } from "react";
import { ScrollView, StyleSheet, View } from "react-native";
import {
  Button,
  Chip,
  HelperText,
  Modal,
  Portal,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { isPremiumRequired, ApiError } from "@futureroots/api-client";
import type { PlannedCall } from "@futureroots/types";
import { api } from "@/api";

interface TimeOption {
  label: string;
  hour: number;
  minute: number;
}

const TIME_OPTIONS: TimeOption[] = [
  { label: "9:00 AM", hour: 9, minute: 0 },
  { label: "12:00 PM", hour: 12, minute: 0 },
  { label: "3:00 PM", hour: 15, minute: 0 },
  { label: "6:00 PM", hour: 18, minute: 0 },
  { label: "8:00 PM", hour: 20, minute: 0 },
];

/** The next 7 calendar days as {label, date-at-midnight}. */
function dayOptions(): { label: string; date: Date }[] {
  const out: { label: string; date: Date }[] = [];
  const base = new Date();
  base.setHours(0, 0, 0, 0);
  for (let i = 0; i < 7; i++) {
    const d = new Date(base);
    d.setDate(base.getDate() + i);
    const label =
      i === 0 ? "Today" : i === 1 ? "Tomorrow" : d.toLocaleDateString("en-US", { weekday: "long" });
    out.push({ label, date: d });
  }
  return out;
}

export function PlannedCallSheet({
  visible,
  familyId,
  initial,
  onDismiss,
  onSaved,
  onPremiumNeeded,
}: {
  visible: boolean;
  familyId: string;
  initial: PlannedCall | null;
  onDismiss: () => void;
  onSaved: () => void;
  onPremiumNeeded: () => void;
}) {
  const theme = useTheme();
  const days = useMemo(dayOptions, []);
  const [dayIndex, setDayIndex] = useState(0);
  const [timeIndex, setTimeIndex] = useState(3); // default to the evening slot
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  // Seed from the existing plan each time the sheet opens.
  useEffect(() => {
    if (!visible) return;
    setError("");
    if (initial) {
      const when = new Date(initial.scheduled_for);
      const di = days.findIndex((d) => d.date.toDateString() === when.toDateString());
      setDayIndex(di >= 0 ? di : 0);
      const ti = TIME_OPTIONS.findIndex((t) => t.hour === when.getHours());
      setTimeIndex(ti >= 0 ? ti : 3);
      setNote(initial.note ?? "");
    } else {
      setDayIndex(0);
      setTimeIndex(3);
      setNote("");
    }
  }, [visible, initial, days]);

  async function save() {
    const day = days[dayIndex];
    const time = TIME_OPTIONS[timeIndex];
    if (!day || !time) return;
    const when = new Date(day.date);
    when.setHours(time.hour, time.minute, 0, 0);
    setBusy(true);
    setError("");
    try {
      await api.setPlannedCall(familyId, when.toISOString(), note.trim() || undefined);
      onSaved();
    } catch (err) {
      if (isPremiumRequired(err)) {
        onPremiumNeeded();
        return;
      }
      setError(err instanceof ApiError ? err.message : "We couldn't save that. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Portal>
      <Modal
        visible={visible}
        onDismiss={busy ? undefined : onDismiss}
        contentContainerStyle={[styles.sheet, { backgroundColor: theme.colors.surface }]}
      >
        <Text variant="titleLarge" style={styles.title}>
          When's the next family call?
        </Text>

        <Text variant="labelLarge" style={styles.groupLabel}>
          Which day
        </Text>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chipRow}>
          {days.map((d, i) => (
            <Chip
              key={d.label}
              selected={dayIndex === i}
              showSelectedCheck={false}
              onPress={() => setDayIndex(i)}
              style={styles.chip}
            >
              {d.label}
            </Chip>
          ))}
        </ScrollView>

        <Text variant="labelLarge" style={styles.groupLabel}>
          What time
        </Text>
        <View style={styles.timeWrap}>
          {TIME_OPTIONS.map((t, i) => (
            <Chip
              key={t.label}
              selected={timeIndex === i}
              showSelectedCheck={false}
              onPress={() => setTimeIndex(i)}
              style={styles.chip}
            >
              {t.label}
            </Chip>
          ))}
        </View>

        <TextInput
          mode="outlined"
          label="A note for the family (optional)"
          placeholder="Sunday catch-up with Grandma"
          value={note}
          onChangeText={setNote}
          style={styles.note}
        />

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <View style={styles.actions}>
          <Button mode="contained" onPress={save} loading={busy} disabled={busy}>
            Save the next call
          </Button>
          <Button mode="text" onPress={onDismiss} disabled={busy}>
            Never mind
          </Button>
        </View>
      </Modal>
    </Portal>
  );
}

const styles = StyleSheet.create({
  sheet: { marginHorizontal: 16, borderRadius: 24, padding: 20, maxHeight: "88%" },
  title: { fontWeight: "700", marginBottom: 8 },
  groupLabel: { marginTop: 12, marginBottom: 8 },
  chipRow: { gap: 8, paddingRight: 8 },
  timeWrap: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  chip: { marginRight: 0 },
  note: { marginTop: 16 },
  actions: { marginTop: 16, gap: 8 },
});
