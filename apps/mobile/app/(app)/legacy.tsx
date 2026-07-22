// Legacy archive — the family's recipes, stories, wisdom, photos, and documents,
// kept for every generation. Mirrors the web archive (apps/web/src/app/family/
// [id]/legacy/page.tsx) in behavior and copy, in a native, one-hand flow.
//
//  - Inspiration prompts point the "Add to the archive" form at a kind with one
//    tap (a full card when the archive is empty, a quiet chip strip once it has
//    items).
//  - Adding reuses the Phase 3 capture + upload helpers for an optional photo,
//    voice note, or video, saved via the family-media upload contract. A video
//    respects the `video_upload` Premium capability (warm upsell + 402 backstop).
//
// The archive is a full-member surface (home hides it for supporters).
import React, { useState } from "react";
import {
  KeyboardAvoidingView,
  Platform,
  RefreshControl,
  ScrollView,
  StyleSheet,
  View,
} from "react-native";
import { Stack } from "expo-router";
import {
  ActivityIndicator,
  Button,
  Card,
  Chip,
  HelperText,
  Text,
  TextInput,
  TouchableRipple,
  useTheme,
} from "react-native-paper";
import { Image } from "expo-image";
import { Audio, ResizeMode, Video } from "expo-av";
import { useQuery } from "@tanstack/react-query";
import type { LegacyType } from "@futureroots/types";
import { ApiError, isPremiumRequired } from "@futureroots/api-client";
import { api, type MobileUpload } from "@/api";
import { queryClient } from "@/query";
import { useActiveFamily } from "@/active-family";
import { familyPhrase } from "@/format";
import { capturePhoto, captureVideo, pickMedia } from "@/capture";
import { mediaSource } from "@/media";
import { MediaView } from "@/components/media-view";
import { PremiumUpsellCard } from "@/components/premium-upsell";

const TYPE_META: Record<LegacyType, { icon: string; label: string; prompt: string }> = {
  story: { icon: "📖", label: "Story", prompt: "Tell a story from the old days" },
  recipe: { icon: "🥧", label: "Recipe", prompt: "Pass down a family recipe" },
  wisdom: { icon: "🦉", label: "Wisdom", prompt: "Record a piece of advice" },
  photo: { icon: "🖼️", label: "Photo", prompt: "Add a cherished old photo" },
  document: { icon: "📜", label: "Document", prompt: "Keep an important document safe" },
};

const TYPE_ORDER: LegacyType[] = ["story", "recipe", "wisdom", "photo", "document"];

export default function LegacyScreen() {
  const theme = useTheme();
  const { activeFamily } = useActiveFamily();
  const familyId = activeFamily?.id;
  const role = activeFamily?.role ?? null;

  const detail = useQuery({
    queryKey: ["family-detail", familyId],
    queryFn: () => api.familyDetail(familyId as string),
    enabled: !!familyId,
  });
  const legacy = useQuery({
    queryKey: ["legacy", familyId],
    queryFn: () => api.listLegacy(familyId as string),
    enabled: !!familyId,
  });

  const familyName = detail.data?.name ?? "";
  const videoAllowed = detail.data ? detail.data.capabilities.includes("video_upload") : true;

  const [formOpen, setFormOpen] = useState(false);
  const [presetType, setPresetType] = useState<LegacyType>("story");

  function openForm(type: LegacyType) {
    setPresetType(type);
    setFormOpen(true);
  }

  function refresh() {
    void legacy.refetch();
    void detail.refetch();
  }

  const items = legacy.data ?? null;

  if (legacy.isLoading || detail.isLoading) {
    return (
      <>
        <Stack.Screen options={{ title: "Legacy archive" }} />
        <View style={styles.center}>
          <ActivityIndicator />
        </View>
      </>
    );
  }

  const isEmpty = (items ?? []).length === 0;

  return (
    <>
      <Stack.Screen options={{ title: "Legacy archive" }} />
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === "ios" ? "padding" : undefined}
        keyboardVerticalOffset={90}
      >
        <ScrollView
          contentContainerStyle={styles.content}
          keyboardShouldPersistTaps="handled"
          refreshControl={<RefreshControl refreshing={legacy.isRefetching} onRefresh={refresh} />}
        >
          <View style={styles.intro}>
            <Text variant="headlineSmall" style={[styles.title, { color: theme.colors.primary }]}>
              Legacy archive 🌳
            </Text>
            <Text variant="bodyMedium" style={{ color: theme.colors.onSurfaceVariant }}>
              {familyName ? `The story of ${familyPhrase(familyName)}.` : "Your family story."} Recipes,
              wisdom, and history, kept for every generation.
            </Text>
          </View>

          {isEmpty ? (
            <Card mode="contained" style={[styles.card, { backgroundColor: theme.colors.primaryContainer }]}>
              <Card.Content style={styles.emptyContent}>
                <Text style={styles.emptyEmoji} accessibilityElementsHidden>
                  🌳
                </Text>
                <Text variant="titleLarge" style={[styles.title, styles.centerText, { color: theme.colors.onPrimaryContainer }]}>
                  Every family has a story. Start yours.
                </Text>
                <Text variant="bodyMedium" style={[styles.centerText, { color: theme.colors.onPrimaryContainer }]}>
                  The archive holds the things worth keeping for generations: recipes in a
                  grandparent's words, the stories behind old photos, the advice you never want lost.
                </Text>
                <View style={styles.promptTiles}>
                  {TYPE_ORDER.map((t) => (
                    <TouchableRipple
                      key={t}
                      onPress={() => openForm(t)}
                      borderless
                      style={[styles.promptTile, { backgroundColor: theme.colors.surface }]}
                    >
                      <View style={styles.promptTileInner}>
                        <Text style={styles.promptIcon} accessibilityElementsHidden>
                          {TYPE_META[t].icon}
                        </Text>
                        <Text variant="bodyMedium" style={styles.promptText}>
                          {TYPE_META[t].prompt}
                        </Text>
                      </View>
                    </TouchableRipple>
                  ))}
                </View>
              </Card.Content>
            </Card>
          ) : (
            <View style={styles.promptStrip}>
              {TYPE_ORDER.map((t) => (
                <Chip key={t} icon={undefined} onPress={() => openForm(t)} style={styles.promptChip}>
                  {TYPE_META[t].icon} Add {TYPE_META[t].label.toLowerCase()}
                </Chip>
              ))}
            </View>
          )}

          {formOpen ? (
            <LegacyForm
              key={presetType}
              familyId={familyId as string}
              initialType={presetType}
              role={role}
              videoAllowed={videoAllowed}
              onClose={() => setFormOpen(false)}
              onAdded={() => {
                setFormOpen(false);
                void queryClient.invalidateQueries({ queryKey: ["legacy", familyId] });
                void queryClient.invalidateQueries({ queryKey: ["feed", familyId] });
                void legacy.refetch();
              }}
            />
          ) : !isEmpty ? (
            <Button mode="contained-tonal" icon="plus" onPress={() => openForm("story")} style={styles.addOpen}>
              Add to the archive
            </Button>
          ) : null}

          <View style={styles.list}>
            {(items ?? []).map((item) => {
              const ct = item.media_content_type ?? "";
              return (
                <Card key={item.id} mode="outlined" style={styles.card}>
                  <Card.Content style={styles.itemContent}>
                    <View style={styles.itemHead}>
                      <Text style={styles.itemIcon} accessibilityElementsHidden>
                        {TYPE_META[item.type].icon}
                      </Text>
                      <View style={styles.itemBody}>
                        <Text variant="titleMedium" style={styles.itemTitle}>
                          {item.title}
                        </Text>
                        <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
                          {TYPE_META[item.type].label} · from {item.created_by_name} ·{" "}
                          {new Date(item.created_at).toLocaleDateString()}
                        </Text>
                        {item.body ? (
                          <Text variant="bodyMedium" style={[styles.itemText, { color: theme.colors.onSurface }]}>
                            {item.body}
                          </Text>
                        ) : null}
                        {item.media_id && (ct.startsWith("image/") || ct.startsWith("video/")) ? (
                          <View style={styles.itemMedia}>
                            <MediaView mediaId={item.media_id} contentType={item.media_content_type} accessibilityLabel={item.title} />
                          </View>
                        ) : null}
                        {item.media_id && ct.startsWith("audio/") ? (
                          <View style={styles.itemMedia}>
                            <Video source={mediaSource(item.media_id)} style={styles.audio} useNativeControls resizeMode={ResizeMode.CONTAIN} accessibilityLabel={item.title} />
                          </View>
                        ) : null}
                      </View>
                    </View>
                  </Card.Content>
                </Card>
              );
            })}
          </View>
        </ScrollView>
      </KeyboardAvoidingView>
    </>
  );
}

function LegacyForm({
  familyId,
  initialType,
  role,
  videoAllowed,
  onAdded,
  onClose,
}: {
  familyId: string;
  initialType: LegacyType;
  role: import("@futureroots/types").FamilyRole | null;
  videoAllowed: boolean;
  onAdded: () => void;
  onClose: () => void;
}) {
  const theme = useTheme();
  const [type, setType] = useState<LegacyType>(initialType);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [media, setMedia] = useState<MobileUpload | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [upsell, setUpsell] = useState(false);

  const recordingRef = React.useRef<Audio.Recording | null>(null);
  const [recording, setRecording] = useState(false);

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
      const { recording: rec } = await Audio.Recording.createAsync(Audio.RecordingOptionsPresets.HIGH_QUALITY);
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

  async function submit() {
    if (!title.trim()) return;
    setBusy(true);
    setError("");
    try {
      const media_id = media ? await api.uploadFamilyMedia(familyId, media) : undefined;
      await api.addLegacy(familyId, {
        type,
        title: title.trim(),
        body: body.trim() || undefined,
        media_id,
      });
      onAdded();
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
        <View style={styles.formHead}>
          <Text variant="titleMedium" style={[styles.title, { color: theme.colors.primary }]}>
            Add to the archive
          </Text>
          <Button mode="text" compact onPress={onClose}>
            Close
          </Button>
        </View>

        <Text variant="bodyMedium" style={{ color: theme.colors.onSurface }}>
          What is it?
        </Text>
        <View style={styles.chipRow}>
          {TYPE_ORDER.map((t) => (
            <Chip key={t} selected={type === t} showSelectedCheck onPress={() => setType(t)} style={styles.typeChip}>
              {TYPE_META[t].icon} {TYPE_META[t].label}
            </Chip>
          ))}
        </View>

        <TextInput
          mode="outlined"
          label="Title"
          placeholder="e.g. Grandma Rose's apple pie"
          value={title}
          onChangeText={setTitle}
        />
        <TextInput
          mode="outlined"
          label="The story itself"
          placeholder="How it was told to me..."
          value={body}
          onChangeText={setBody}
          multiline
          style={styles.storyInput}
        />

        <MediaPreview media={media} onClear={() => setMedia(null)} />

        {recording ? (
          <Card mode="contained" style={[styles.recordCard, { backgroundColor: theme.colors.primaryContainer }]}>
            <Card.Content style={styles.recordContent}>
              <Text style={styles.recordDot} accessibilityElementsHidden>
                🎙️
              </Text>
              <Text variant="bodyMedium" style={{ color: theme.colors.onPrimaryContainer }}>
                Recording. Take your time and tell it your way.
              </Text>
              <Button mode="contained" icon="stop" onPress={onStopVoice} style={styles.recordStop}>
                Stop and keep it
              </Button>
            </Card.Content>
          </Card>
        ) : (
          <View style={styles.attachRow}>
            <Text variant="bodySmall" style={{ color: theme.colors.onSurfaceVariant }}>
              Photo, recording, or scan (optional)
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

        {error ? (
          <HelperText type="error" visible>
            {error}
          </HelperText>
        ) : null}

        <Button
          mode="contained"
          onPress={submit}
          loading={busy}
          disabled={busy || !title.trim() || recording}
          style={styles.submitBtn}
          contentStyle={styles.submitContent}
        >
          Add to the archive
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
              Recording ready to save
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
  content: { padding: 16, gap: 16 },
  intro: { gap: 4 },
  title: { fontWeight: "700" },
  centerText: { textAlign: "center" },
  card: { borderRadius: 16 },
  emptyContent: { alignItems: "center", gap: 10 },
  emptyEmoji: { fontSize: 40 },
  promptTiles: { alignSelf: "stretch", gap: 8, marginTop: 6 },
  promptTile: { borderRadius: 14 },
  promptTileInner: { flexDirection: "row", alignItems: "center", gap: 12, padding: 14 },
  promptIcon: { fontSize: 24 },
  promptText: { flex: 1, fontWeight: "600" },
  promptStrip: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  promptChip: {},
  addOpen: { borderRadius: 12, alignSelf: "flex-start" },
  list: { gap: 12 },
  itemContent: {},
  itemHead: { flexDirection: "row", gap: 12 },
  itemIcon: { fontSize: 24, lineHeight: 30 },
  itemBody: { flex: 1, minWidth: 0, gap: 3 },
  itemTitle: { fontWeight: "700" },
  itemText: { marginTop: 2 },
  itemMedia: { marginTop: 8 },
  audio: { width: "100%", height: 54 },
  formContent: { gap: 12 },
  formHead: { flexDirection: "row", alignItems: "center", justifyContent: "space-between" },
  chipRow: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  typeChip: {},
  storyInput: {},
  previewWrap: { gap: 4 },
  preview: { width: "100%", height: 220, borderRadius: 16, backgroundColor: "#00000010" },
  filePreview: { borderRadius: 16 },
  filePreviewRow: { flexDirection: "row", alignItems: "center", gap: 12 },
  fileIcon: { fontSize: 26 },
  clearBtn: { alignSelf: "flex-start" },
  attachRow: { gap: 8 },
  attachButtons: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  attachBtn: { borderRadius: 12 },
  recordCard: { borderRadius: 16 },
  recordContent: { alignItems: "center", gap: 8, paddingVertical: 8 },
  recordDot: { fontSize: 32 },
  recordStop: { borderRadius: 12, alignSelf: "stretch", marginTop: 4 },
  submitBtn: { borderRadius: 12, marginTop: 4 },
  submitContent: { paddingVertical: 8 },
});
