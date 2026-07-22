// Add a memory / milestone — the native capture flow.
//
// A tile chooser (Take a photo, Record a video, Record a voice note, Choose
// from library, Add a document, Write a note, Celebrate a milestone) leads into
// a single compose step: an optional media preview plus a title and a few
// words, saved to the child's vault via the shared create -> PUT -> complete
// upload contract (api.uploadMedia) and the vault/milestone create endpoints.
//
// The video tiles respect the `video_upload` Premium capability: on a Free
// family they show the warm upsell instead of the recorder/picker. Photos,
// voice notes, documents, notes, and milestones are always free. The server
// enforces the same gate on the upload ticket, so a slipped-through video is
// caught and turned back into the upsell rather than an error.
import React, { useEffect, useRef, useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { Stack, useLocalSearchParams, useRouter } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Checkbox,
  HelperText,
  Text,
  TextInput,
  useTheme,
} from "react-native-paper";
import { Image } from "expo-image";
import { Audio, ResizeMode, Video } from "expo-av";
import { useQuery } from "@tanstack/react-query";
import type { VaultItemType } from "@futureroots/types";
import { ApiError, isPremiumRequired } from "@futureroots/api-client";
import { api, type MobileUpload } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import {
  capturePhoto,
  captureVideo,
  pickDocument,
  pickMedia,
} from "@/capture";
import { PremiumUpsellCard } from "@/components/premium-upsell";

type Kind = "photo" | "video" | "voice" | "message" | "document" | "milestone";
type Stage = "choose" | "recording" | "compose";

const TILES: { kind: Exclude<Kind, "video"> | "video"; icon: string; label: string }[] = [
  { kind: "photo", icon: "camera", label: "Take a photo" },
  { kind: "video", icon: "video", label: "Record a video" },
  { kind: "voice", icon: "microphone", label: "Record a voice note" },
  { kind: "message", icon: "pencil", label: "Write a note" },
  { kind: "document", icon: "file-document-outline", label: "Add a document" },
  { kind: "milestone", icon: "party-popper", label: "Celebrate a milestone" },
];

function vaultTypeFor(kind: Kind): VaultItemType {
  switch (kind) {
    case "video":
      return "video";
    case "voice":
      return "voice";
    case "document":
      return "document";
    case "message":
      return "message";
    default:
      return "photo";
  }
}

export default function AddMemoryScreen() {
  const router = useRouter();
  const { childId } = useLocalSearchParams<{ childId: string }>();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const role = activeFamily?.role ?? null;
  const isParent = role === "parent";

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const child = detail.data?.children.find((c) => c.id === childId) ?? null;
  const childName = child?.first_name ?? "";
  // Affordance only; the API's upload ticket enforces the real gate. Before the
  // detail loads we optimistically allow and rely on that 402 backstop.
  const videoAllowed = detail.data
    ? detail.data.capabilities.includes("video_upload")
    : true;

  const [stage, setStage] = useState<Stage>("choose");
  const [kind, setKind] = useState<Kind>("photo");
  const [media, setMedia] = useState<MobileUpload | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [share, setShare] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [upsell, setUpsell] = useState(false);

  // --- voice recording (expo-av) ---
  const recordingRef = useRef<Audio.Recording | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);

  useEffect(() => {
    // Safety net: if the screen unmounts mid-recording, release the hardware.
    return () => {
      void recordingRef.current?.stopAndUnloadAsync().catch(() => {});
    };
  }, []);

  useEffect(() => {
    if (stage !== "recording") return;
    const started = Date.now();
    setElapsedMs(0);
    const id = setInterval(() => setElapsedMs(Date.now() - started), 250);
    return () => clearInterval(id);
  }, [stage]);

  function reset() {
    setMedia(null);
    setTitle("");
    setBody("");
    setShare(false);
    setError("");
    setUpsell(false);
    setStage("choose");
  }

  function toCompose(k: Kind, file: MobileUpload | null) {
    setKind(k);
    setMedia(file);
    setError("");
    setUpsell(false);
    setStage("compose");
  }

  async function onTile(k: Kind) {
    setError("");
    setUpsell(false);
    try {
      if (k === "photo") {
        const file = await capturePhoto();
        if (file) toCompose("photo", file);
      } else if (k === "video") {
        if (!videoAllowed) {
          setKind("video");
          setUpsell(true);
          return;
        }
        const file = await captureVideo();
        if (file) toCompose("video", file);
      } else if (k === "document") {
        const file = await pickDocument();
        if (file) toCompose("document", file);
      } else if (k === "message") {
        toCompose("message", null);
      } else if (k === "milestone") {
        toCompose("milestone", null);
      } else if (k === "voice") {
        await startRecording();
      }
    } catch {
      setError("Something went wrong opening that. Please try again.");
    }
  }

  // "Choose from library" can return a photo or a video; the Premium gate is
  // checked once we know which it is.
  async function onPickLibrary() {
    setError("");
    setUpsell(false);
    try {
      const file = await pickMedia();
      if (!file) return;
      const isVideo = file.contentType.startsWith("video/");
      if (isVideo && !videoAllowed) {
        setKind("video");
        setUpsell(true);
        return;
      }
      toCompose(isVideo ? "video" : "photo", file);
    } catch {
      setError("We couldn't open your library. Please try again.");
    }
  }

  // Optional attachment for a milestone (mirrors the web milestone form's
  // optional photo/video), reusing the same gate.
  async function attachToMilestone() {
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

  async function startRecording() {
    const perm = await Audio.requestPermissionsAsync();
    if (!perm.granted) {
      setError("We need permission to use the microphone to record a voice note.");
      return;
    }
    await Audio.setAudioModeAsync({ allowsRecordingIOS: true, playsInSilentModeIOS: true });
    const { recording } = await Audio.Recording.createAsync(
      Audio.RecordingOptionsPresets.HIGH_QUALITY
    );
    recordingRef.current = recording;
    setKind("voice");
    setStage("recording");
  }

  async function stopRecording() {
    const recording = recordingRef.current;
    recordingRef.current = null;
    if (!recording) {
      setStage("choose");
      return;
    }
    await recording.stopAndUnloadAsync().catch(() => {});
    await Audio.setAudioModeAsync({ allowsRecordingIOS: false }).catch(() => {});
    const uri = recording.getURI();
    if (uri) toCompose("voice", { uri, contentType: "audio/m4a" });
    else {
      setError("That recording didn't save. Please try again.");
      setStage("choose");
    }
  }

  async function cancelRecording() {
    const recording = recordingRef.current;
    recordingRef.current = null;
    await recording?.stopAndUnloadAsync().catch(() => {});
    await Audio.setAudioModeAsync({ allowsRecordingIOS: false }).catch(() => {});
    reset();
  }

  async function save() {
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const media_id = media ? await api.uploadMedia(childId, media) : undefined;
      const created =
        kind === "milestone"
          ? await api.postMilestone(childId, {
              title: title.trim(),
              description: body.trim() || undefined,
              media_id,
            })
          : await api.addVaultItem(childId, {
              type: vaultTypeFor(kind),
              title: title.trim(),
              body: body.trim() || undefined,
              media_id,
            });
      if (isParent && share && created?.id) {
        await api.setVaultVisibility(created.id, true);
      }
      // Refresh the surfaces this touches: the vault list, the child's Future
      // Gifts score, and the family feed.
      void queryClient.invalidateQueries({ queryKey: ["vault", childId] });
      void queryClient.invalidateQueries({ queryKey: ["family-detail", familyId] });
      void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
      router.back();
    } catch (err) {
      if (isPremiumRequired(err)) {
        // Server-side gate backstop: show the warm invitation, never an error.
        setUpsell(true);
      } else {
        setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  const screenTitle =
    stage === "compose" && kind === "milestone" ? "Celebrate a milestone" : "Add a memory";

  if (detail.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: screenTitle }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  return (
    <>
      <Stack.Screen options={{ title: screenTitle }} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
          {stage === "choose" ? (
            <ChooseStage
              childName={childName}
              onTile={onTile}
              onPickLibrary={onPickLibrary}
              upsell={upsell}
              role={role}
              onDismissUpsell={() => setUpsell(false)}
            />
          ) : null}

          {stage === "recording" ? (
            <RecordingStage
              elapsedMs={elapsedMs}
              onStop={stopRecording}
              onCancel={cancelRecording}
            />
          ) : null}

          {stage === "compose" ? (
            <>
              <MediaPreview media={media} />

              {kind === "milestone" && !media ? (
                <Button
                  mode="outlined"
                  icon="image-plus"
                  onPress={attachToMilestone}
                  style={styles.attach}
                >
                  Add a photo or video (optional)
                </Button>
              ) : null}

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

              <TextInput
                mode="outlined"
                label={kind === "milestone" ? "What happened?" : "Title"}
                placeholder={
                  kind === "milestone"
                    ? `e.g. ${childName || "Emma"}'s first piano recital`
                    : "e.g. Sunday at the lake"
                }
                value={title}
                onChangeText={setTitle}
                style={styles.input}
              />
              <TextInput
                mode="outlined"
                label={kind === "milestone" ? "Tell the story (optional)" : "A few words (optional)"}
                value={body}
                onChangeText={setBody}
                multiline
                style={styles.input}
              />

              {isParent ? (
                <Checkbox.Item
                  label="Allow supporters to see this"
                  status={share ? "checked" : "unchecked"}
                  onPress={() => setShare((v) => !v)}
                  position="leading"
                  style={styles.checkbox}
                  labelStyle={styles.checkboxLabel}
                />
              ) : null}

              {error ? (
                <HelperText type="error" visible>
                  {error}
                </HelperText>
              ) : null}

              <Button
                mode="contained"
                onPress={save}
                loading={busy}
                disabled={busy || upsell || !title.trim()}
                style={styles.save}
                contentStyle={styles.saveContent}
              >
                {kind === "milestone" ? "Share the news" : "Save to the vault"}
              </Button>
              <Button mode="text" onPress={reset} disabled={busy} style={styles.back}>
                Choose something else
              </Button>
            </>
          ) : null}
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

function ChooseStage({
  childName,
  onTile,
  onPickLibrary,
  upsell,
  role,
  onDismissUpsell,
}: {
  childName: string;
  onTile: (k: Kind) => void;
  onPickLibrary: () => void;
  upsell: boolean;
  role: import("@futureroots/types").FamilyRole | null;
  onDismissUpsell: () => void;
}) {
  const theme = useTheme();
  return (
    <>
      <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
        Add a memory
      </Text>
      <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
        A photo, a video, a voice note, or a few words for {childName || "them"} to treasure later.
      </Text>

      {upsell ? (
        <PremiumUpsellCard capability="video_upload" role={role} onDismiss={onDismissUpsell} />
      ) : null}

      <View style={styles.tiles}>
        {TILES.map((t) => (
          <CaptureTile
            key={t.kind}
            icon={t.icon}
            label={t.label}
            onPress={() => onTile(t.kind)}
          />
        ))}
        {/* Library pick sits with the tiles but has its own handler (it can
            yield a photo or a video). */}
        <CaptureTile icon="image-multiple" label="Choose from library" onPress={onPickLibrary} />
      </View>
    </>
  );
}

function CaptureTile({
  icon,
  label,
  onPress,
}: {
  icon: string;
  label: string;
  onPress: () => void;
}) {
  return (
    <Button
      mode="outlined"
      icon={icon}
      onPress={onPress}
      style={styles.tile}
      contentStyle={styles.tileContent}
      labelStyle={styles.tileLabel}
      accessibilityLabel={label}
    >
      {label}
    </Button>
  );
}

function RecordingStage({
  elapsedMs,
  onStop,
  onCancel,
}: {
  elapsedMs: number;
  onStop: () => void;
  onCancel: () => void;
}) {
  const theme = useTheme();
  const secs = Math.floor(elapsedMs / 1000);
  const mmss = `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")}`;
  return (
    <Card mode="contained" style={[styles.recordCard, { backgroundColor: theme.colors.primaryContainer }]}>
      <Card.Content style={styles.recordContent}>
        <Text style={styles.recordDot} accessibilityElementsHidden>
          🎙️
        </Text>
        <Text variant="headlineMedium" style={{ color: theme.colors.onPrimaryContainer }}>
          {mmss}
        </Text>
        <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
          Recording a voice note. Say something they will love to hear.
        </Text>
        <Button
          mode="contained"
          icon="stop"
          onPress={onStop}
          style={styles.recordStop}
          contentStyle={styles.saveContent}
        >
          Stop and keep it
        </Button>
        <Button mode="text" onPress={onCancel}>
          Cancel
        </Button>
      </Card.Content>
    </Card>
  );
}

function MediaPreview({ media }: { media: MobileUpload | null }) {
  const theme = useTheme();
  if (!media) return null;
  if (media.contentType.startsWith("image/")) {
    return (
      <Image
        source={{ uri: media.uri }}
        style={styles.preview}
        contentFit="cover"
        accessibilityLabel="The photo you just added"
      />
    );
  }
  if (media.contentType.startsWith("video/")) {
    return (
      <Video
        source={{ uri: media.uri }}
        style={styles.preview}
        useNativeControls
        resizeMode={ResizeMode.CONTAIN}
      />
    );
  }
  const isAudio = media.contentType.startsWith("audio/");
  return (
    <Card mode="outlined" style={styles.filePreview}>
      <Card.Content style={styles.filePreviewRow}>
        <Text style={styles.fileIcon} accessibilityElementsHidden>
          {isAudio ? "🎙️" : "📄"}
        </Text>
        <Text variant="bodyLarge" style={{ color: theme.colors.onSurface }}>
          {isAudio ? "Voice note ready to save" : "File ready to save"}
        </Text>
      </Card.Content>
    </Card>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center" },
  content: { padding: 16, gap: 14 },
  title: { fontWeight: "700" },
  tiles: { gap: 12, marginTop: 4 },
  tile: { borderRadius: 14 },
  tileContent: { paddingVertical: 14, justifyContent: "flex-start" },
  tileLabel: { fontSize: 17 },
  recordCard: { borderRadius: 20, marginTop: 8 },
  recordContent: { alignItems: "center", gap: 10, paddingVertical: 12 },
  recordDot: { fontSize: 40 },
  recordStop: { borderRadius: 12, marginTop: 8, alignSelf: "stretch" },
  preview: { width: "100%", height: 260, borderRadius: 16, backgroundColor: "#00000010" },
  filePreview: { borderRadius: 16 },
  filePreviewRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  fileIcon: { fontSize: 28 },
  attach: { borderRadius: 12 },
  input: {},
  checkbox: { paddingHorizontal: 0 },
  checkboxLabel: { textAlign: "left" },
  save: { borderRadius: 12, marginTop: 4 },
  saveContent: { paddingVertical: 8 },
  back: { marginTop: 2 },
});
