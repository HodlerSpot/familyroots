// Family Video Call helpers: just-in-time permission priming and small pure
// formatters for the in-call surface.
//
// We prime camera + microphone BEFORE handing the channel to react-native-agora
// so the OS prompt appears in a warm, expected moment (right after the member
// taps to join) rather than mid-connect. Neither is required to join: the call
// screen degrades to audio-only, or to watch-and-listen, based on what was
// granted (mirrors the web no-camera/no-mic fallbacks).
import * as ImagePicker from "expo-image-picker";
import { Audio } from "expo-av";

export interface CallPermissions {
  camera: boolean;
  mic: boolean;
}

/** Ask for camera + microphone access. Returns what was granted; callers never
 * block the call on a denial, they just publish fewer tracks. */
export async function primeCallPermissions(): Promise<CallPermissions> {
  // Run both prompts; a denial on one must not skip the other.
  const [cam, mic] = await Promise.all([
    ImagePicker.requestCameraPermissionsAsync().catch(() => null),
    Audio.requestPermissionsAsync().catch(() => null),
  ]);
  return { camera: !!cam?.granted, mic: !!mic?.granted };
}

/** The warm banner shown at the top of the call when the member joined without
 * full media access. Empty string means "everything is fine, show nothing". */
export function mediaFallbackNote(perms: CallPermissions): string {
  if (perms.camera && perms.mic) return "";
  if (!perms.camera && !perms.mic) {
    return "You can still see and hear everyone here.";
  }
  if (!perms.camera) {
    return "You've joined with just your voice. Everyone can still hear you.";
  }
  // Mic denied but camera allowed: they can be seen, not heard.
  return "You've joined with just your camera. Everyone can still see you.";
}

/** "5:07" / "1:02:30" elapsed clock. Mirrors web formatElapsed. */
export function formatElapsed(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  const pad = (n: number) => String(n).padStart(2, "0");
  return h > 0 ? `${h}:${pad(m)}:${pad(sec)}` : `${m}:${pad(sec)}`;
}

/** Warm one-liner summarizing who is on the call, from the roster. */
export function summarizeParticipants(names: string[]): string {
  const n = names.length;
  if (n === 0) return "The family call is starting.";
  if (n === 1) return `${names[0]} ${names[0] === "You" ? "are" : "is"} on the call now.`;
  if (n === 2) return `${names[0]} and ${names[1]} are on the call now.`;
  return `${names[0]}, ${names[1]} and ${n - 2} ${n - 2 === 1 ? "other" : "others"} are on the call now.`;
}
