// Time Capsules — sealed letters, photos, voice notes, and videos a child opens
// on a future day. Mirrors the web CapsulesSection (apps/web/src/components/
// capsules.tsx) in behavior and copy, tuned for a native, one-hand flow.
//
//  - The list shows sealed capsules (a locked card with the release condition)
//    and opened ones (the letter + any media). Only the author sees their own
//    sealed letter's text as a faint preview.
//  - "Seal a capsule" opens a form: a letter, an optional photo / voice note /
//    video (reusing the Phase 3 capture + upload helpers), and a release
//    condition (an age, a date, a life moment, or reaching a goal).
//  - Life-moment capsules open by agreement: the author can open theirs any
//    time, and guardians can add their vote. The vote gate + eligibility come
//    straight from the API DTO (can_vote / i_voted / release_votes / is_mine),
//    the same as web, so the GUARDIAN_ROLES rule stays server-owned.
//  - A video attachment respects the `video_upload` Premium capability: on a
//    Free family the warm upsell shows instead of the recorder/picker, and the
//    server's 402 on the upload ticket is caught as a final backstop.
//
// Capsules live inside the guardians' circle, so this screen is only reached by
// full members (the vault hides the entry for supporters).
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
  Chip,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { Image } from "expo-image";
import { Audio, ResizeMode, Video } from "expo-av";
import { useQuery } from "@tanstack/react-query";
import type {
  CapsuleOut,
  CapsuleType,
  GoalOut,
  ReleaseCondition,
} from "@futureroots/types";
import { ApiError, isPremiumRequired } from "@futureroots/api-client";
import { api, type MobileUpload } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { capturePhoto, captureVideo, pickMedia } from "@/capture";
import { mediaSource } from "@/media";
import { MediaView } from "@/components/media-view";
import { PremiumUpsellCard } from "@/components/premium-upsell";

function conditionLabel(c: CapsuleOut): string {
  switch (c.release_condition) {
    case "age":
      return `Opens when they turn ${c.release_age}`;
    case "date":
      return `Opens ${new Date((c.release_date ?? "") + "T00:00:00").toLocaleDateString()}`;
    case "milestone":
      return `Opens at: ${c.release_milestone}`;
    case "goal":
      return `Opens when they reach '${c.release_goal_title}'`;
  }
}

const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

export default function CapsulesScreen() {
  const theme = useTheme();
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const role = activeFamily?.role ?? null;

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const child = detail.data?.children.find((c) => c.id === childId) ?? null;
  const childName = child?.first_name ?? "";
  // Affordance only; the upload ticket enforces the real gate (402 backstop).
  const videoAllowed = detail.data ? detail.data.capabilities.includes("video_upload") : true;

  const capsules = useQuery({
    queryKey: ["capsules", childId],
    queryFn: () => api.listCapsules(childId),
    enabled: !!childId,
  });
  const goals = useQuery({
    queryKey: ["goals", childId],
    queryFn: () => api.listGoals(childId),
    enabled: !!childId,
  });

  const [showForm, setShowForm] = useState(false);
  const [error, setError] = useState("");

  function refresh() {
    void capsules.refetch();
    void goals.refetch();
    void detail.refetch();
  }

  async function release(capsuleId: string) {
    setError("");
    try {
      await api.releaseCapsule(capsuleId);
      void queryClient.invalidateQueries({ queryKey: ["capsules", childId] });
      void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
      void capsules.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    }
  }

  async function vote(capsuleId: string) {
    setError("");
    try {
      await api.voteReleaseCapsule(capsuleId);
      void queryClient.invalidateQueries({ queryKey: ["capsules", childId] });
      void capsules.refetch();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    }
  }

  const list = capsules.data ?? [];
  const incompleteGoals = (goals.data ?? []).filter((g) => g.status === "active");

  if (detail.isLoading || capsules.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: "Time capsules" }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: "Time capsules" }} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            <RefreshControl refreshing={capsules.isRefetching} onRefresh={refresh} />
          }
        >
          <View style={styles.headerRow}>
            <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
              Time capsules
            </Text>
            <Button
              mode={showForm ? "text" : "contained-tonal"}
              onPress={() => setShowForm((v) => !v)}
              icon={showForm ? undefined : "email-seal-outline"}
            >
              {showForm ? "Close" : "Seal a capsule"}
            </Button>
          </View>

          {error ? (
            <HelperText type="error" visible>
              {error}
            </HelperText>
          ) : null}

          {showForm ? (
            <CapsuleForm
              childId={childId}
              childName={childName}
              incompleteGoals={incompleteGoals}
              role={role}
              videoAllowed={videoAllowed}
              onSealed={() => {
                setShowForm(false);
                void queryClient.invalidateQueries({ queryKey: ["capsules", childId] });
                void queryClient.invalidateQueries({ queryKey: ["family-detail", familyId] });
                void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
                void capsules.refetch();
                void detail.refetch();
              }}
            />
          ) : null}

          {list.length === 0 && !showForm ? (
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurfaceVariant }}>
              Seal a letter or recording today. {childName || "They"} will open it years from now,
              right when it matters most.
            </Text>
          ) : null}

          <View style={styles.list}>
            {list.map((c) =>
              c.status === "sealed" ? (
                <SealedCard
                  key={c.id}
                  capsule={c}
                  onOpen={() => release(c.id)}
                  onVote={() => vote(c.id)}
                />
              ) : (
                <OpenedCard key={c.id} capsule={c} />
              )
            )}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

/** A locked capsule: who it's from and when it opens. Life-moment capsules
 * carry the author's "Open now" and guardians' agreement vote. */
function SealedCard({
  capsule: c,
  onOpen,
  onVote,
}: {
  capsule: CapsuleOut;
  onOpen: () => void;
  onVote: () => void;
}) {
  const theme = useTheme();
  const showVoteArea = c.release_condition === "milestone";
  return (
    <Card mode="outlined" style={[styles.card, styles.sealedCard]}>
      <Card.Content style={styles.sealedContent}>
        <View style={styles.sealedText}>
          <Text variant="titleMedium" style={styles.cardHeading}>
            🔒 Sealed capsule
          </Text>
          <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
            From {c.is_mine ? "you" : c.created_by_name} · {conditionLabel(c)}
          </Text>
          {c.is_mine && c.body ? (
            <Text
              variant="bodyMedium"
              numberOfLines={2}
              style={[styles.sealedPreview, { color: theme.colors.onSurfaceVariant }]}
            >
              &ldquo;{c.body}&rdquo;
            </Text>
          ) : null}
        </View>
        {showVoteArea ? (
          <View style={styles.voteArea}>
            {c.is_mine ? (
              <Button mode="contained-tonal" compact onPress={onOpen}>
                Open now
              </Button>
            ) : null}
            {c.can_vote ? (
              <Button mode="contained-tonal" compact onPress={onVote}>
                I agree it's time to open this
              </Button>
            ) : null}
            {c.can_vote || c.i_voted || c.release_votes > 0 ? (
              <Text variant="bodySmall" style={[styles.voteMeta, { color: theme.colors.onSurfaceVariant }]}>
                {c.i_voted
                  ? "You agreed. Waiting for one more."
                  : `${c.release_votes} of 2 guardians agreed`}
              </Text>
            ) : null}
          </View>
        ) : null}
      </Card.Content>
    </Card>
  );
}

/** An opened capsule: the letter and any media, on display for the family. */
function OpenedCard({ capsule: c }: { capsule: CapsuleOut }) {
  const theme = useTheme();
  const ct = c.media_content_type ?? "";
  return (
    <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.secondaryContainer }]}>
      <Card.Content style={styles.openedContent}>
        <Text variant="titleMedium" style={[styles.cardHeading, { color: theme.colors.onSecondaryContainer }]}>
          💌 From {c.created_by_name}
        </Text>
        {c.body ? (
          <Text variant="bodyLarge" style={{ color: theme.colors.onSecondaryContainer }}>
            {c.body}
          </Text>
        ) : null}
        {c.media_id && (ct.startsWith("image/") || ct.startsWith("video/")) ? (
          <View style={styles.openedMedia}>
            <MediaView
              mediaId={c.media_id}
              contentType={c.media_content_type}
              accessibilityLabel={`Time capsule from ${c.created_by_name}`}
            />
          </View>
        ) : null}
        {c.media_id && ct.startsWith("audio/") ? (
          <AudioNote mediaId={c.media_id} />
        ) : null}
        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
          Sealed {new Date(c.created_at).toLocaleDateString()}
          {c.released_at ? ` · opened ${new Date(c.released_at).toLocaleDateString()}` : ""}
        </Text>
      </Card.Content>
    </Card>
  );
}

/** A small player for an opened voice-note capsule (expo-av, session header). */
function AudioNote({ mediaId }: { mediaId: string }) {
  const source = mediaSource(mediaId);
  return (
    <View style={styles.audioWrap}>
      <Video
        source={source}
        style={styles.audio}
        useNativeControls
        resizeMode={ResizeMode.CONTAIN}
        accessibilityLabel="A voice note sealed for the future"
      />
    </View>
  );
}

const CONDITIONS: { value: ReleaseCondition; label: string }[] = [
  { value: "age", label: "At an age" },
  { value: "date", label: "On a date" },
  { value: "milestone", label: "At a life moment" },
  { value: "goal", label: "When they reach a goal" },
];

function CapsuleForm({
  childId,
  childName,
  incompleteGoals,
  role,
  videoAllowed,
  onSealed,
}: {
  childId: string;
  childName: string;
  incompleteGoals: GoalOut[];
  role: import("@futureroots/types").FamilyRole | null;
  videoAllowed: boolean;
  onSealed: () => void;
}) {
  const theme = useTheme();
  const [body, setBody] = useState("");
  const [media, setMedia] = useState<MobileUpload | null>(null);
  const [condition, setCondition] = useState<ReleaseCondition>("age");
  const [age, setAge] = useState("18");
  const [dateValue, setDateValue] = useState("");
  const [milestone, setMilestone] = useState("");
  const [goalId, setGoalId] = useState(incompleteGoals[0]?.id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [upsell, setUpsell] = useState(false);

  const recordingRef = React.useRef<Audio.Recording | null>(null);
  const [recording, setRecording] = useState(false);

  const hasGoals = incompleteGoals.length > 0;

  React.useEffect(() => {
    return () => {
      void recordingRef.current?.stopAndUnloadAsync().catch(() => {});
    };
  }, []);

  async function onAttachPhoto() {
    setError("");
    try {
      const file = await capturePhoto();
      if (file) setMedia(file);
    } catch {
      setError("We couldn't open the camera. Please try again.");
    }
  }

  async function onAttachLibrary() {
    setError("");
    try {
      const file = await pickMedia();
      if (!file) return;
      if (file.contentType.startsWith("video/") && !videoAllowed) {
        setUpsell(true);
        return;
      }
      setMedia(file);
    } catch {
      setError("We couldn't open your library. Please try again.");
    }
  }

  async function onAttachVideo() {
    setError("");
    if (!videoAllowed) {
      setUpsell(true);
      return;
    }
    try {
      const file = await captureVideo();
      if (file) setMedia(file);
    } catch {
      setError("We couldn't open the camera. Please try again.");
    }
  }

  async function onRecordVoice() {
    setError("");
    try {
      const perm = await Audio.requestPermissionsAsync();
      if (!perm.granted) {
        setError("We need permission to use the microphone to record a voice note.");
        return;
      }
      await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
      const { recording: rec } = await Audio.Recording.createAsync(
        Audio.RecordingOptionsPresets.HIGH_QUALITY
      );
      recordingRef.current = rec;
      setRecording(true);
    } catch {
      setError("We couldn't start recording. Please try again.");
    }
  }

  async function onStopVoice() {
    const rec = recordingRef.current;
    recordingRef.current = null;
    setRecording(false);
    if (!rec) return;
    await rec.stopAndUnloadAsync().catch(() => {});
    await Audio.setAudioModeAsync({ allowsRecordingIOS: false }).catch(() => {});
    const uri = rec.getURI();
    if (uri) setMedia({ uri, contentType: "audio/m4a" });
    else setError("That recording didn't save. Please try again.");
  }

  function capsuleTypeFor(file: MobileUpload | null): CapsuleType {
    if (!file) return "letter";
    if (file.contentType.startsWith("video/")) return "video";
    if (file.contentType.startsWith("audio/")) return "audio";
    return "letter";
  }

  const conditionReady =
    (condition === "age" && !!age && Number(age) > 0) ||
    (condition === "date" && ISO_DATE.test(dateValue)) ||
    (condition === "milestone" && milestone.trim().length > 0) ||
    (condition === "goal" && !!goalId);
  const hasContent = body.trim().length > 0 || media !== null;
  const canSeal = hasContent && conditionReady && !recording;

  async function seal() {
    if (!canSeal) return;
    setBusy(true);
    setError("");
    try {
      const media_id = media ? await api.uploadMedia(childId, media) : undefined;
      await api.createCapsule(childId, {
        type: capsuleTypeFor(media),
        body: body.trim() || undefined,
        media_id,
        release_condition: condition,
        release_age: condition === "age" ? parseInt(age, 10) : undefined,
        release_date: condition === "date" ? dateValue : undefined,
        release_milestone: condition === "milestone" ? milestone.trim() : undefined,
        release_goal_id: condition === "goal" ? goalId : undefined,
      });
      onSealed();
    } catch (err) {
      if (isPremiumRequired(err)) {
        setUpsell(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
      setBusy(false);
    }
  }

  return (
    <Card mode="outlined" style={styles.card}>
      <Card.Content style={styles.formContent}>
        <Text variant="titleMedium" style={[styles.cardHeading, { color: theme.colors.primary }]}>
          ✉️ A message for the future
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
          Only you can see it until the day it opens.
        </Text>

        <TextInput
          mode="outlined"
          label={`Your letter to ${childName || "them"}`}
          placeholder={`Dear ${childName || "Emma"}, today you...`}
          value={body}
          onChangeText={setBody}
          multiline
          style={styles.letter}
        />

        <MediaPreview media={media} onClear={() => setMedia(null)} />

        {recording ? (
          <Card mode="contained" style={[styles.recordCard, { backgroundColor: theme.colors.primaryContainer }]}>
            <Card.Content style={styles.recordContent}>
              <Text style={styles.recordDot} accessibilityElementsHidden>
                🎙️
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
                Recording a voice note. Say something they will love to hear.
              </Text>
              <Button mode="contained" icon="stop" onPress={onStopVoice} style={styles.recordStop}>
                Stop and keep it
              </Button>
            </Card.Content>
          </Card>
        ) : (
          <View style={styles.attachRow}>
            <Text variant="bodySmall" style={[styles.attachLabel, { color: theme.colors.onSurfaceVariant }]}>
              Add a photo, voice note, or video (optional)
            </Text>
            <View style={styles.attachButtons}>
              <Button mode="outlined" compact icon="camera" onPress={onAttachPhoto} style={styles.attachBtn}>
                Photo
              </Button>
              <Button mode="outlined" compact icon="microphone" onPress={onRecordVoice} style={styles.attachBtn}>
                Voice
              </Button>
              <Button mode="outlined" compact icon="video" onPress={onAttachVideo} style={styles.attachBtn}>
                Video
              </Button>
              <Button mode="outlined" compact icon="image-multiple" onPress={onAttachLibrary} style={styles.attachBtn}>
                Library
              </Button>
            </View>
          </View>
        )}

        {upsell ? (
          <PremiumUpsellCard
            capability="video_upload"
            role={role}
            onDismiss={() => {
              setUpsell(false);
              if (media?.contentType.startsWith("video/")) setMedia(null);
            }}
          />
        ) : null}

        <Text variant="bodyMedium" style={[styles.whenLabel, { color: theme.colors.onSurface }]}>
          When should it open?
        </Text>
        <View style={styles.chipRow}>
          {CONDITIONS.map((c) => {
            const disabled = c.value === "goal" && !hasGoals;
            return (
              <Chip
                key={c.value}
                selected={condition === c.value}
                disabled={disabled}
                showSelectedCheck
                onPress={() => {
                  setCondition(c.value);
                  if (c.value === "goal" && !goalId) setGoalId(incompleteGoals[0]?.id ?? "");
                }}
                style={styles.conditionChip}
              >
                {c.label}
              </Chip>
            );
          })}
        </View>
        {!hasGoals ? (
          <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
            Create a goal first to link a capsule to it.
          </Text>
        ) : null}

        {condition === "age" ? (
          <TextInput
            mode="outlined"
            label="Their age"
            keyboardType="number-pad"
            value={age}
            onChangeText={setAge}
            style={styles.condInput}
          />
        ) : null}
        {condition === "date" ? (
          <>
            <TextInput
              mode="outlined"
              label="The date"
              placeholder="YYYY-MM-DD"
              value={dateValue}
              onChangeText={setDateValue}
              autoCapitalize="none"
              style={styles.condInput}
            />
            <HelperText type="info" visible>
              Type the date as year-month-day, for example 2035-06-14.
            </HelperText>
          </>
        ) : null}
        {condition === "milestone" ? (
          <TextInput
            mode="outlined"
            label="The moment"
            placeholder="e.g. Graduation day"
            value={milestone}
            onChangeText={setMilestone}
            style={styles.condInput}
          />
        ) : null}
        {condition === "goal" && hasGoals ? (
          <View style={styles.goalChoice}>
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
              Which goal?
            </Text>
            <View style={styles.chipRow}>
              {incompleteGoals.map((g) => (
                <Chip
                  key={g.id}
                  selected={goalId === g.id}
                  showSelectedCheck
                  onPress={() => setGoalId(g.id)}
                  style={styles.conditionChip}
                >
                  {g.title}
                </Chip>
              ))}
            </View>
          </View>
        ) : null}

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <Button
          mode="contained"
          onPress={seal}
          loading={busy}
          disabled={busy || !canSeal}
          style={styles.sealBtn}
          contentStyle={styles.sealContent}
        >
          Seal it for the future
        </Button>
      </Card.Content>
    </Card>
  );
}

function MediaPreview({ media, onClear }: { media: MobileUpload | null; onClear: () => void }) {
  const theme = useTheme();
  if (!media) return null;
  const isImage = media.contentType.startsWith("image/");
  const isVideo = media.contentType.startsWith("video/");
  return (
    <View style={styles.previewWrap}>
      {isImage ? (
        <Image source={{ uri: media.uri }} style={styles.preview} contentFit="cover" accessibilityLabel="The photo you attached" />
      ) : isVideo ? (
        <Video source={{ uri: media.uri }} style={styles.preview} useNativeControls resizeMode={ResizeMode.CONTAIN} />
      ) : (
        <Card mode="outlined" style={styles.filePreview}>
          <Card.Content style={styles.filePreviewRow}>
            <Text style={styles.fileIcon} accessibilityElementsHidden>
              🎙️
            </Text>
            <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
              Voice note ready to seal
            </Text>
          </Card.Content>
        </Card>
      )}
      <Button mode="text" compact onPress={onClear} style={styles.clearBtn}>
        Remove attachment
      </Button>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 14 },
  headerRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 8 },
  title: { fontWeight: "700", flexShrink: 1 },
  list: { gap: 12 },
  card: { borderRadius: 16 },
  cardHeading: { fontWeight: "700" },
  sealedCard: { borderStyle: "dashed" },
  sealedContent: { gap: 10 },
  sealedText: { gap: 4 },
  sealedPreview: { fontStyle: "italic", opacity: 0.85 },
  voteArea: { gap: 6, alignItems: "flex-start" },
  voteMeta: {},
  openedContent: { gap: 8 },
  openedMedia: { marginTop: 4 },
  audioWrap: { marginTop: 4 },
  audio: { width: "100%", height: 54 },
  formContent: { gap: 12 },
  letter: {},
  previewWrap: { gap: 4 },
  preview: { width: "100%", height: 220, borderRadius: 16, backgroundColor: "#00000010" },
  filePreview: { borderRadius: 16 },
  filePreviewRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  fileIcon: { fontSize: 26 },
  clearBtn: { alignSelf: "flex-start" },
  attachRow: { gap: 8 },
  attachLabel: {},
  attachButtons: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  attachBtn: { borderRadius: 12 },
  recordCard: { borderRadius: 16 },
  recordContent: { alignItems: "center", gap: 8, paddingVertical: 8 },
  recordDot: { fontSize: 32 },
  recordStop: { borderRadius: 12, alignSelf: "stretch", marginTop: 4 },
  whenLabel: { fontWeight: "600", marginTop: 4 },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  conditionChip: {},
  condInput: {},
  goalChoice: { gap: 6 },
  sealBtn: { borderRadius: 12, marginTop: 4 },
  sealContent: { paddingVertical: 8 },
});
