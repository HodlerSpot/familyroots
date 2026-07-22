// Native media display helper.
//
// The mobile api-client runs in `media: { mode: "header" }`, so `mediaUrl(id)`
// returns a bare `${apiUrl}/media/{id}` with no query credential. The media
// endpoint accepts a session bearer directly (apps/api/app/routers/vault.py),
// so we display protected images/videos by attaching an `Authorization: Bearer`
// header on the request the native image/video loader makes.
//
// Both expo-image (<Image source={{ uri, headers }}>) and expo-av
// (<Video source={{ uri, headers }}>) accept a `headers` map on their source,
// which is exactly where this token goes. Read the token fresh on each call so
// a silent refresh (SessionController) is always reflected.
import { getToken, mediaUrl } from "./api";

/** A source object for <Image>/<Video>: the media URL plus the bearer header
 * the API expects. Returns no header when there is no session (defensive). */
export function mediaSource(mediaId: string): { uri: string; headers?: Record<string, string> } {
  const token = getToken();
  return {
    uri: mediaUrl(mediaId),
    ...(token ? { headers: { Authorization: `Bearer ${token}` } } : {}),
  };
}

/** True when a stored media item is a video, from its content type. Vault
 * items carry `media_content_type`; feed events carry it in the payload. */
export function isVideoContentType(contentType: string | null | undefined): boolean {
  return typeof contentType === "string" && contentType.startsWith("video/");
}
