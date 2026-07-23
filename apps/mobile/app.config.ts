import type { ExpoConfig } from "expo/config";

// Which environment this build/config resolution targets. EAS build profiles
// (see eas.json) set APP_ENV; `expo start` locally defaults to development.
type AppEnv = "development" | "preview" | "production";
const APP_ENV = (process.env.APP_ENV as AppEnv) || "development";

// The FastAPI base URL per environment, surfaced to the app via
// expo-constants (`Constants.expoConfig.extra.apiUrl`). Dev talks to the
// local uvicorn server; preview/production talk to the deployed API.
const API_URL: Record<AppEnv, string> = {
  development: "http://localhost:8000",
  preview: "https://api.futureroots.app",
  production: "https://api.futureroots.app",
};

const config: ExpoConfig = {
  name: "FutureRoots",
  slug: "futureroots",
  owner: "futureroots-mobile",
  scheme: "futureroots",
  version: "0.1.0",
  orientation: "portrait",
  // Placeholder brand assets derived from docs/brand/logo.png (copied into
  // ./assets so they resolve within the project root); Phase 6 replaces them
  // with properly sized icon/splash exports.
  icon: "./assets/icon.png",
  userInterfaceStyle: "automatic",
  newArchEnabled: true,
  splash: {
    image: "./assets/splash.png",
    resizeMode: "contain",
    backgroundColor: "#ffffff",
  },
  assetBundlePatterns: ["**/*"],
  ios: {
    bundleIdentifier: "com.futureroots.mobile",
    supportsTablet: true,
    // Universal Links: emailed/in-app https links (reset-password, invites,
    // family, legacy) open the app when the AASA file is served from the domain,
    // and fall back to the web otherwise. Server-side AASA is tracked in the
    // build plan; this is the app-side declaration.
    associatedDomains: ["applinks:futureroots.app", "applinks:www.futureroots.app"],
  },
  android: {
    package: "com.futureroots.mobile",
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#ffffff",
    },
    // Android App Links: same https paths, auto-verified against the domain's
    // assetlinks.json (server-side, tracked in the build plan).
    intentFilters: [
      {
        action: "VIEW",
        autoVerify: true,
        data: [
          { scheme: "https", host: "futureroots.app", pathPrefix: "/reset-password" },
          { scheme: "https", host: "futureroots.app", pathPrefix: "/invites" },
          { scheme: "https", host: "futureroots.app", pathPrefix: "/family" },
          { scheme: "https", host: "futureroots.app", pathPrefix: "/legacy" },
          { scheme: "https", host: "www.futureroots.app", pathPrefix: "/reset-password" },
        ],
        category: ["BROWSABLE", "DEFAULT"],
      },
    ],
  },
  plugins: [
    "expo-router",
    "expo-secure-store",
    "expo-local-authentication",
    // In-app browser for the Stripe hosted flows (Premium checkout / gift /
    // billing portal). The return bridge bounces back to the futureroots://
    // scheme, which openAuthSessionAsync intercepts to close the browser.
    "expo-web-browser",
    // Native push. No parameters needed; APNs/FCM credentials live in EAS.
    "expo-notifications",
    // Native capture permissions (Add a memory flow): camera + library + mic.
    [
      "expo-image-picker",
      {
        photosPermission:
          "FutureRoots uses your photos so you can add memories to a child's vault.",
        cameraPermission:
          "FutureRoots uses the camera so you can capture photos and videos for a child's vault.",
        microphonePermission:
          "FutureRoots uses the microphone so you can record videos for a child's vault.",
      },
    ],
    // Voice notes are recorded with expo-av; declare the mic usage string.
    [
      "expo-av",
      {
        microphonePermission:
          "FutureRoots uses the microphone so you can record a voice note for a child's vault.",
      },
    ],
    // Stripe PaymentSheet (Contribute flow). merchantIdentifier powers Apple Pay;
    // enableGooglePay turns on the Google Pay sheet on Android. The publishable
    // key itself is public and travels in `extra` (below), never here.
    [
      "@stripe/stripe-react-native",
      {
        merchantIdentifier: "merchant.com.futureroots.mobile",
        enableGooglePay: true,
      },
    ],
    // Family Video Call (react-native-agora). Local config plugin (see
    // ./plugins/withAgora.js) because react-native-agora ships no Expo plugin:
    // it adds the Android call permissions and, as a fallback, iOS camera/mic
    // usage strings if the capture plugins above haven't already set them. The
    // native module links via autolinking, so a `expo prebuild` + dev-client
    // build is required to run the call (it does not work in Expo Go).
    [
      "./plugins/withAgora",
      {
        cameraPermission:
          "FutureRoots uses the camera so you can see and be seen on a family video call.",
        microphonePermission:
          "FutureRoots uses the microphone so everyone can hear you on a family video call.",
      },
    ],
  ],
  extra: {
    appEnv: APP_ENV,
    apiUrl: API_URL[APP_ENV],
    // Stripe publishable key is public (it only creates client-side tokens), so
    // it is safe to ship in the bundle. It is injected from the environment at
    // build/start time (EAS env or a local .env), never hardcoded here. When
    // unset, the Contribute flow falls back to a warm "payments not ready" note
    // just like the web app does.
    stripePublishableKey: process.env.STRIPE_PUBLISHABLE_KEY ?? "",
    // Populated once the founder provisions the EAS project.
    eas: { projectId: "" },
  },
};

export default config;
