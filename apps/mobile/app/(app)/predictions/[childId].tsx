// Future Predictions — the yearly family word-cloud game.
//
// One screen holds the whole ritual, mirroring the web surfaces
// (apps/web/src/components/predictions/*) in behavior and copy:
//  - The OPEN round: a live word cloud rendered client-side from the API's
//    {word, weight} list, a composer capped at three predictions per member per
//    year (with the remaining count), and the attributed list where you can
//    edit or remove your own (parents/guardians can remove any).
//  - The sealed-years strip (family only): locked years waiting for the 18th
//    birthday, a surprise for everyone including the family.
//  - The released Book of Predictions (family only): each sealed year's keepsake
//    image and the full attributed list, once the child turns 18.
//
// Supporters may play the open round and watch the cloud grow, but the API
// returns `year` and `seals_on` as null and `completed` as false for them, so
// they never see a birthdate, a seal date, or a sealed/released round. We rely
// on those nulls rather than reconstructing anything client-side.
import React, { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { Stack, useLocalSearchParams } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { useQuery } from "@tanstack/react-query";
import type {
  CloudWordOut,
  OpenRoundOut,
  PredictionOut,
} from "@futureroots/types";
import { ApiError } from "@futureroots/api-client";
import { api } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { MediaView } from "@/components/media-view";

const MAX_LEN = 120;
const MIN_LEN = 2;

function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

/** The seal line. A supporter's payload has `seals_on === null` (the API strips
 * the birthdate-derived date), so a null date IS the supporter signal: we never
 * reconstruct a date or countdown for them. */
function sealLine(name: string, sealsOn: string | null): string {
  const who = name || "them";
  if (!sealsOn) return `Seals on ${who}'s next birthday.`;
  const when = new Date(sealsOn + "T00:00:00").toLocaleDateString(undefined, {
    month: "long",
    day: "numeric",
  });
  return `Seals on ${who}'s birthday, ${when}.`;
}

export default function PredictionsScreen() {
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { isSupporter } = useActiveFamily();

  const game = useQuery({
    queryKey: ["predictions", childId],
    queryFn: () => api.getPredictionGame(childId),
    enabled: !!childId,
  });

  // Family-only: the locked years. Self-hides when empty; skipped for supporters
  // (the endpoint is family-only and would carry a date they must not see).
  const sealed = useQuery({
    queryKey: ["predictions-sealed", childId],
    queryFn: () => api.listSealedPredictionRounds(childId),
    enabled: !!childId && !isSupporter,
  });

  const completed = game.data?.round === null && game.data?.completed === true;
  // The released Book, only once the round is gone and the book has opened.
  const book = useQuery({
    queryKey: ["predictions-book", childId],
    queryFn: () => api.getPredictionBook(childId),
    enabled: !!childId && !isSupporter && completed,
  });

  async function refresh() {
    await game.refetch();
    if (!isSupporter) {
      void sealed.refetch();
      if (completed) void book.refetch();
    }
  }

  if (game.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: "Future predictions" }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  const data = game.data ?? null;
  const name = data?.child_first_name || "";
  const round = data?.round ?? null;

  return (
    <>
      <Stack.Screen options={{ title: "Future predictions" }} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={game.isRefetching} onRefresh={refresh} />}
        >
          {game.isError ? (
            <HelperText type="error" visible>
              We couldn't load predictions just now. Pull down to try again.
            </HelperText>
          ) : null}

          {round ? (
            <OpenRoundCard
              round={round}
              name={name}
              childId={childId}
              onChanged={() => game.refetch()}
            />
          ) : completed ? (
            <BookSection name={name} loading={book.isLoading} chapters={book.data?.chapters ?? []} />
          ) : (
            <EmptyState name={name} isSupporter={isSupporter} />
          )}

          {!isSupporter && (sealed.data ?? []).length > 0 ? (
            <SealedYears
              name={name}
              rounds={sealed.data ?? []}
            />
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

/** The open round: cloud + composer (with remaining count) + attributed list. */
function OpenRoundCard({
  round,
  name,
  childId,
  onChanged,
}: {
  round: OpenRoundOut;
  name: string;
  childId: string;
  onChanged: () => void;
}) {
  const theme = useTheme();
  const used = round.my_prediction_ids.length;
  const remaining = Math.max(0, round.max_per_member - used);

  async function add(body: string) {
    await api.addPrediction(childId, body);
    // Refetch so the server-computed cloud, list, and slot count stay exact.
    void queryClient.invalidateQueries({ queryKey: ["predictions", childId] });
    onChanged();
  }

  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.roundContent}>
        <View style={styles.roundHead}>
          <Text variant="titleLarge" style={[styles.heading, { color: theme.colors.primary }]}>
            🔮 Predictions for {name || "them"}
          </Text>
          {round.year !== null ? (
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              {round.year}
            </Text>
          ) : null}
        </View>
        <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
          In a few words, what do you imagine for {name || "them"}? Everyone's guesses grow the cloud
          below. {sealLine(name, round.seals_on)}
        </Text>

        <View style={[styles.cloudBox, { backgroundColor: theme.colors.surfaceVariant }]}>
          <WordCloud words={round.cloud} />
        </View>

        {remaining > 0 ? (
          <>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              {used === 0
                ? `You can add up to ${round.max_per_member} predictions this year.`
                : `${remaining} more ${remaining === 1 ? "prediction" : "predictions"} to add this year.`}
            </Text>
            <Composer childName={name} onAdd={add} />
          </>
        ) : (
          <Text variant="bodyMedium" style={{ color: theme.colors.primary }}>
            You've added all {round.max_per_member} of your predictions for this year. You can still
            edit or remove them below until the round seals.
          </Text>
        )}

        {round.predictions.length > 0 ? (
          <View style={styles.rows}>
            {round.predictions.map((p) => (
              <PredictionRow key={p.id} pred={p} childId={childId} onChanged={onChanged} />
            ))}
          </View>
        ) : null}
      </Card.Content>
    </Card>
  );
}

/** The live word cloud, sized by weight. Client-rendered so it updates the
 * instant a prediction is added or edited. Cycles three theme colors (the same
 * intent as the web keepsake palette), theme-aware for light and dark. */
function WordCloud({ words }: { words: CloudWordOut[] }) {
  const theme = useTheme();
  const colorsCycle = [theme.colors.primary, theme.colors.secondary, theme.colors.onSurfaceVariant];

  if (words.length === 0) {
    return (
      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
        No words yet. Add the first prediction and watch it appear here.
      </Text>
    );
  }

  const weights = words.map((w) => w.weight);
  const min = Math.min(...weights);
  const max = Math.max(...weights);
  const sizeFor = (weight: number): number => {
    if (max === min) return 24;
    return Math.round(16 + 26 * ((weight - min) / (max - min)));
  };

  return (
    <View
      style={styles.cloud}
      accessibilityLabel="The words the family has predicted, larger where more people said the same thing"
    >
      {words.map((w, i) => (
        <Text
          key={w.word}
          style={{
            fontSize: sizeFor(w.weight),
            lineHeight: sizeFor(w.weight) + 4,
            fontWeight: "700",
            color: colorsCycle[i % colorsCycle.length],
          }}
          accessibilityLabel={`${w.word}, said ${w.weight} ${w.weight === 1 ? "time" : "times"}`}
        >
          {w.word}
        </Text>
      ))}
    </View>
  );
}

/** The add field. The 4th add returns a warm 409 the API writes; we surface it. */
function Composer({
  childName,
  onAdd,
}: {
  childName: string;
  onAdd: (body: string) => Promise<void>;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = draft.trim();
  const tooLong = draft.length > MAX_LEN;

  async function submit() {
    if (trimmed.length < MIN_LEN || tooLong) return;
    setBusy(true);
    setError("");
    try {
      await onAdd(trimmed);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't add that just now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <View style={styles.composer}>
      <TextInput
        mode="outlined"
        value={draft}
        onChangeText={setDraft}
        maxLength={MAX_LEN}
        placeholder={`What will ${childName || "they"} grow up to do?`}
        accessibilityLabel="Add a prediction"
        right={<TextInput.Affix text={`${draft.length}/${MAX_LEN}`} />}
      />
      {error ? (
        <HelperText type="error" visible>
          {error}
        </HelperText>
      ) : null}
      <Button
        mode="contained"
        onPress={submit}
        loading={busy}
        disabled={busy || trimmed.length < MIN_LEN}
        style={styles.addBtn}
      >
        Add your prediction
      </Button>
    </View>
  );
}

/** One attributed prediction, with inline edit + two-step remove for the
 * viewer's own (remove-only for parents/guardians moderating). */
function PredictionRow({
  pred,
  childId,
  onChanged,
}: {
  pred: PredictionOut;
  childId: string;
  onChanged: () => void;
}) {
  const theme = useTheme();
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(pred.body);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const trimmed = draft.trim();

  async function save() {
    if (trimmed.length < MIN_LEN || trimmed.length > MAX_LEN) {
      setError(`A prediction is ${MIN_LEN} to ${MAX_LEN} characters.`);
      return;
    }
    setBusy(true);
    setError("");
    try {
      await api.editPrediction(pred.id, trimmed);
      setEditing(false);
      void queryClient.invalidateQueries({ queryKey: ["predictions", childId] });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't save that just now.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError("");
    try {
      await api.deletePrediction(pred.id);
      void queryClient.invalidateQueries({ queryKey: ["predictions", childId] });
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We couldn't remove that just now.");
      setBusy(false);
      setConfirming(false);
    }
  }

  if (editing) {
    return (
      <View style={[styles.row, { backgroundColor: theme.colors.surfaceVariant }]}>
        <TextInput
          mode="outlined"
          value={draft}
          onChangeText={setDraft}
          maxLength={MAX_LEN}
          accessibilityLabel="Edit your prediction"
          autoFocus
          right={<TextInput.Affix text={`${draft.length}/${MAX_LEN}`} />}
        />
        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}
        <View style={styles.rowActions}>
          <Button
            mode="text"
            compact
            disabled={busy}
            onPress={() => {
              setEditing(false);
              setDraft(pred.body);
              setError("");
            }}
          >
            Cancel
          </Button>
          <Button mode="contained-tonal" compact loading={busy} disabled={busy || trimmed.length < MIN_LEN} onPress={save}>
            Save
          </Button>
        </View>
      </View>
    );
  }

  return (
    <View style={[styles.row, { backgroundColor: theme.colors.surfaceVariant }]}>
      <View style={styles.rowHead}>
        <Text variant="bodyMedium" style={styles.author}>
          {pred.author_name}
          {pred.is_mine ? <Text style={{ color: theme.colors.primary }}> (you)</Text> : null}
        </Text>
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
          {timeAgo(pred.created_at)}
        </Text>
      </View>
      <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
        {pred.body}
      </Text>
      {pred.can_delete ? (
        <View style={styles.rowActions}>
          {pred.is_mine ? (
            <Button mode="text" compact disabled={busy} onPress={() => setEditing(true)}>
              Edit
            </Button>
          ) : null}
          {confirming ? (
            <>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant, alignSelf: "center" }}>
                Remove this?
              </Text>
              <Button mode="text" compact textColor={theme.colors.error} loading={busy} disabled={busy} onPress={remove}>
                Yes, remove
              </Button>
              <Button mode="text" compact disabled={busy} onPress={() => setConfirming(false)}>
                Keep
              </Button>
            </>
          ) : (
            <Button mode="text" compact disabled={busy} onPress={() => setConfirming(true)}>
              Remove
            </Button>
          )}
        </View>
      ) : null}
      {error ? (
        <HelperText type="error" visible>
          {error}
        </HelperText>
      ) : null}
    </View>
  );
}

/** Family-only strip of locked years. No counts, no content, no peek. */
function SealedYears({
  name,
  rounds,
}: {
  name: string;
  rounds: import("@futureroots/types").SealedRoundOut[];
}) {
  const theme = useTheme();
  const who = name || "them";
  const opensOn = new Date(rounds[0].opens_on + "T00:00:00").toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.sealedContent}>
        <Text variant="titleMedium" style={[styles.heading, { color: theme.colors.primary }]}>
          🔒 Sealed predictions
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
          These years are sealed and stay a surprise for everyone, including you, until {who}'s 18th
          birthday ({opensOn}).
        </Text>
        <View style={styles.sealedList}>
          {rounds.map((r) => (
            <View key={r.id} style={[styles.sealedRow, { backgroundColor: theme.colors.surfaceVariant }]}>
              <Text variant="bodyLarge" style={styles.author}>
                {r.year}
              </Text>
              <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                Sealed · opens on the 18th birthday
              </Text>
            </View>
          ))}
        </View>
      </Card.Content>
    </Card>
  );
}

/** The released Book of Predictions: one chapter per sealed year. */
function BookSection({
  name,
  loading,
  chapters,
}: {
  name: string;
  loading: boolean;
  chapters: import("@futureroots/types").BookChapterOut[];
}) {
  const theme = useTheme();
  const who = name || "them";

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }

  return (
    <View style={styles.bookWrap}>
      <View>
        <Text variant="headlineSmall" style={[styles.heading, { color: theme.colors.primary }]}>
          📖 {who}'s Book of Predictions
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
          Years of the family imagining who {who} would become.
        </Text>
      </View>

      {chapters.length === 0 ? (
        <Card mode="outlined" style={styles.card}>
          <Card.Content>
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurfaceVariant }}>
              The book opens on the 18th birthday. When it does, every sealed year of the family's
              predictions appears here together.
            </Text>
          </Card.Content>
        </Card>
      ) : (
        chapters.map((ch) => (
          <Card key={ch.round_id} mode="outlined" style={styles.card}>
            <Card.Content style={styles.chapterContent}>
              <View style={styles.roundHead}>
                <Text variant="titleLarge" style={[styles.heading, { color: theme.colors.primary }]}>
                  {ch.year}
                </Text>
                <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
                  The year {who} turned {ch.age}
                </Text>
              </View>
              {ch.cloud_media_id ? (
                <MediaView
                  mediaId={ch.cloud_media_id}
                  contentType={ch.media_content_type}
                  accessibilityLabel={`The family's predictions for ${who} in ${ch.year}`}
                />
              ) : null}
              <View style={styles.rows}>
                {ch.predictions.map((p, i) => (
                  <View key={`${ch.round_id}-${i}`} style={[styles.row, { backgroundColor: theme.colors.surfaceVariant }]}>
                    <View style={styles.rowHead}>
                      <Text variant="bodyMedium" style={styles.author}>
                        {p.author_name}
                      </Text>
                      <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                        {new Date(p.created_at).toLocaleDateString()}
                      </Text>
                    </View>
                    <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
                      {p.body}
                    </Text>
                  </View>
                ))}
              </View>
            </Card.Content>
          </Card>
        ))
      )}
    </View>
  );
}

/** Nothing to show yet: a supporter with no open round, or a child aged out. */
function EmptyState({ name, isSupporter }: { name: string; isSupporter: boolean }) {
  const theme = useTheme();
  const who = name || "this little one";
  return (
    <View style={styles.empty}>
      <Text style={styles.emptyEmoji} accessibilityElementsHidden>
        🔮
      </Text>
      <Text variant="titleMedium" style={[styles.heading, styles.emptyText, { color: theme.colors.primary }]}>
        Nothing to guess just now
      </Text>
      <Text variant="bodyMedium" style={[styles.emptyText, { color: theme.colors.onSurfaceVariant }]}>
        {isSupporter
          ? `When the family opens a new round of predictions for ${who}, you'll be able to add yours here.`
          : `A new round of predictions for ${who} will open here soon.`}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", paddingVertical: 40 },
  content: { padding: 16, gap: 16 },
  card: { borderRadius: 16 },
  heading: { fontWeight: "700" },
  roundContent: { gap: 12 },
  roundHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 8, flexWrap: "wrap" },
  cloudBox: { borderRadius: 14, padding: 16 },
  cloud: { flexDirection: "row", flexWrap: "wrap", alignItems: "baseline", columnGap: 14, rowGap: 4 },
  composer: { gap: 8 },
  addBtn: { borderRadius: 12 },
  rows: { gap: 8 },
  row: { borderRadius: 14, paddingHorizontal: 12, paddingVertical: 10, gap: 4 },
  rowHead: { flexDirection: "row", alignItems: "baseline", justifyContent: "space-between", gap: 8 },
  author: { fontWeight: "700" },
  rowActions: { flexDirection: "row", flexWrap: "wrap", alignItems: "center", gap: 4, marginTop: 2 },
  sealedContent: { gap: 10 },
  sealedList: { gap: 8, marginTop: 2 },
  sealedRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8, borderRadius: 14, paddingHorizontal: 12, paddingVertical: 10 },
  bookWrap: { gap: 16 },
  chapterContent: { gap: 12 },
  empty: { alignItems: "center", gap: 8, paddingVertical: 32 },
  emptyEmoji: { fontSize: 48 },
  emptyText: { textAlign: "center" },
});
