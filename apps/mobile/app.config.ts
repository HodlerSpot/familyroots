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
    bundleIdentifier: "com.futureroots.app",
    supportsTablet: true,
    // Universal Links: emailed/in-app https links (reset-password, invites,
    // family, legacy) open the app when the AASA file is served from the domain,
    // and fall back to the web otherwise. Server-side AASA is tracked in the
    // build plan; this is the app-side declaration.
    associatedDomains: ["applinks:futureroots.app", "applinks:www.futureroots.app"],
  },
  android: {
    package: "app.futureroots",
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
  plugins: ["expo-router", "expo-secure-store", "expo-local-authentication"],
  extra: {
    appEnv: APP_ENV,
    apiUrl: API_URL[APP_ENV],
    // Populated once the founder provisions the EAS project.
    eas: { projectId: "" },
  },
};

export default config;
