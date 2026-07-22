// Displays a stored media item (photo or video) with the session bearer header
// the media endpoint requires (see src/media.ts). Photos render via expo-image
// (fast, cached); videos via expo-av's <Video> with native controls.
import React from "react";
import { StyleSheet, View } from "react-native";
import { Image } from "expo-image";
import { ResizeMode, Video } from "expo-av";
import { mediaSource, isVideoContentType } from "@/media";

export function MediaView({
  mediaId,
  contentType,
  accessibilityLabel,
}: {
  mediaId: string;
  contentType?: string | null;
  accessibilityLabel?: string;
}) {
  const source = mediaSource(mediaId);

  if (isVideoContentType(contentType)) {
    return (
      <View style={styles.frame}>
        <Video
          source={source}
          style={styles.media}
          useNativeControls
          resizeMode={ResizeMode.CONTAIN}
          accessibilityLabel={accessibilityLabel ?? "Family video"}
        />
      </View>
    );
  }

  return (
    <Image
      source={source}
      style={styles.media}
      contentFit="cover"
      transition={150}
      accessibilityLabel={accessibilityLabel ?? "Family photo"}
    />
  );
}

const styles = StyleSheet.create({
  frame: { borderRadius: 16, overflow: "hidden", backgroundColor: "#000" },
  media: { width: "100%", height: 240, borderRadius: 16 },
});
