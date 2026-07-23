// Native capture helpers for the Add a memory flow.
//
// Each helper returns a MobileUpload (a local content URI + its MIME type) ready
// to hand to `api.uploadMedia`, or null when the member backs out or hasn't
// granted permission. Voice notes are recorded statefully in the screen with
// expo-av; everything else (camera, library, documents) resolves in one shot
// here so the screen stays declarative.
import * as ImagePicker from "expo-image-picker";
import * as DocumentPicker from "expo-document-picker";
import type { MobileUpload } from "./api";

function assetContentType(asset: ImagePicker.ImagePickerAsset): string {
  if (asset.mimeType) return asset.mimeType;
  return asset.type === "video" ? "video/mp4" : "image/jpeg";
}

/** Open the camera for a still photo. Returns null if permission is denied
 * or the member cancels. */
export async function capturePhoto(): Promise<MobileUpload | null> {
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) return null;
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["images"],
    quality: 0.85,
  });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, contentType: assetContentType(asset) };
}

/** Open the camera to record a video. (Only reached on a Premium family; the
 * screen shows the upsell first on a Free one.) */
export async function captureVideo(): Promise<MobileUpload | null> {
  const perm = await ImagePicker.requestCameraPermissionsAsync();
  if (!perm.granted) return null;
  const result = await ImagePicker.launchCameraAsync({
    mediaTypes: ["videos"],
    quality: 0.85,
    videoMaxDuration: 120,
  });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, contentType: assetContentType(asset) };
}

/** Pick a photo or video from the device library. The returned contentType
 * tells the screen whether it is a photo or a video (which the Premium gate
 * checks before uploading). */
export async function pickMedia(): Promise<MobileUpload | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) return null;
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images", "videos"],
    quality: 0.85,
  });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, contentType: assetContentType(asset) };
}

/** Pick a photo (images only) from the library. Used for profile avatars,
 * where a video would make no sense. Returns null if permission is denied or
 * the member cancels. */
export async function pickImage(): Promise<MobileUpload | null> {
  const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
  if (!perm.granted) return null;
  const result = await ImagePicker.launchImageLibraryAsync({
    mediaTypes: ["images"],
    quality: 0.85,
  });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return { uri: asset.uri, contentType: assetContentType(asset) };
}

/** Pick any document (a PDF, a report card, a certificate). */
export async function pickDocument(): Promise<MobileUpload | null> {
  const result = await DocumentPicker.getDocumentAsync({ copyToCacheDirectory: true });
  if (result.canceled || result.assets.length === 0) return null;
  const asset = result.assets[0];
  return {
    uri: asset.uri,
    contentType: asset.mimeType ?? "application/octet-stream",
  };
}
