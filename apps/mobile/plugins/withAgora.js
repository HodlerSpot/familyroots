// Local Expo config plugin for react-native-agora (the Family Video Call).
//
// react-native-agora 4.x does not ship an Expo config plugin, and there is no
// published community plugin, so we carry a small one here. The native module
// itself is picked up by autolinking during `expo prebuild`; this plugin only
// adds the platform config that autolinking can't infer:
//
//   - Android: the runtime permissions Agora needs to open the camera, the
//     microphone, and the audio route (Bluetooth headsets included). Duplicates
//     with the capture plugins (CAMERA / RECORD_AUDIO / MODIFY_AUDIO_SETTINGS)
//     are de-duplicated by withPermissions, so this is purely additive.
//   - iOS: the camera + microphone usage strings, set only if some earlier
//     plugin (expo-image-picker / expo-av) hasn't already written them, so we
//     never clobber the memory-capture wording. A device dev-client build
//     (`expo prebuild` + EAS/`run:ios`/`run:android`) is required to exercise
//     the native call; it cannot run in Expo Go.
const {
  AndroidConfig,
  withInfoPlist,
  createRunOncePlugin,
} = require("@expo/config-plugins");

const pkg = { name: "with-agora", version: "1.0.0" };

// The permission set Agora recommends for a video call. INTERNET and
// ACCESS_NETWORK_STATE are for the media transport; CAMERA/RECORD_AUDIO for
// capture; MODIFY_AUDIO_SETTINGS/BLUETOOTH(_CONNECT) for routing to speakers
// and headsets; WAKE_LOCK keeps the media session alive while the call is up.
const ANDROID_PERMISSIONS = [
  "android.permission.INTERNET",
  "android.permission.ACCESS_NETWORK_STATE",
  "android.permission.RECORD_AUDIO",
  "android.permission.CAMERA",
  "android.permission.MODIFY_AUDIO_SETTINGS",
  "android.permission.BLUETOOTH",
  "android.permission.BLUETOOTH_CONNECT",
  "android.permission.WAKE_LOCK",
];

function withAgoraIosUsage(config, { cameraPermission, microphonePermission }) {
  return withInfoPlist(config, (cfg) => {
    if (cameraPermission && !cfg.modResults.NSCameraUsageDescription) {
      cfg.modResults.NSCameraUsageDescription = cameraPermission;
    }
    if (microphonePermission && !cfg.modResults.NSMicrophoneUsageDescription) {
      cfg.modResults.NSMicrophoneUsageDescription = microphonePermission;
    }
    return cfg;
  });
}

/** @type {import('@expo/config-plugins').ConfigPlugin<{ cameraPermission?: string; microphonePermission?: string }>} */
const withAgora = (config, props = {}) => {
  config = AndroidConfig.Permissions.withPermissions(config, ANDROID_PERMISSIONS);
  config = withAgoraIosUsage(config, props);
  return config;
};

module.exports = createRunOncePlugin(withAgora, pkg.name, pkg.version);
