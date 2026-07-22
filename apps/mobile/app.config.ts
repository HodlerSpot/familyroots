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
  },
  android: {
    package: "app.futureroots",
    adaptiveIcon: {
      foregroundImage: "./assets/adaptive-icon.png",
      backgroundColor: "#ffffff",
    },
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
