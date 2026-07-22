// The feed-event -> warm one-line summary mapping, lifted from the web app's
// apps/web/src/components/feed.tsx `eventLine` so the native feed renders each
// moment type with the same icon and copy (including the prediction events).
import { type FeedEventOut, formatMoney } from "@futureroots/types";
import { familyPhrase } from "./format";

/** An icon + a single warm line describing one feed event. */
export function eventLine(e: FeedEventOut): { icon: string; text: string } {
  const p = e.payload;
  switch (e.type) {
    case "milestone":
      return { icon: "🎉", text: `${p.child_name}: ${p.title}` };
    case "memory_added":
      return {
        icon:
          p.item_type === "photo"
            ? "📷"
            : p.item_type === "video"
              ? "🎬"
              : p.item_type === "message"
                ? "💬"
                : "📎",
        text: `${e.actor_name} added a memory for ${p.child_name}: "${p.title}"`,
      };
    case "member_joined":
      return { icon: "🌱", text: `${p.member_name} joined the family as a ${p.role}` };
    case "member_left":
      // A quiet, no-shame goodbye. Everything they shared stays in the vault.
      return { icon: "🕊️", text: `${p.member_name} has stepped away from the family` };
    case "achievement":
      return { icon: "🏅", text: `${p.child_name} reached a goal: ${p.title}` };
    case "capsule_created":
      return { icon: "✉️", text: `${p.created_by_name} sealed a time capsule for ${p.child_name}` };
    case "capsule_released":
      return {
        icon: "💌",
        text: `A time capsule from ${p.created_by_name} just opened for ${p.child_name}`,
      };
    case "contribution":
      return {
        icon: "💝",
        text: `${p.contributor_name} added ${formatMoney(Number(p.amount_cents))} to ${p.child_name}'s future fund`,
      };
    case "fund_activated":
      return { icon: "💰", text: `${p.child_name}'s Future Fund is ready for gifts` };
    case "premium_activated":
      return {
        icon: "🌟",
        text: `${
          p.family_name ? familyPhrase(String(p.family_name), { capitalize: true }) : "The family"
        } is now on FutureRoots Premium`,
      };
    case "premium_gifted":
      return {
        icon: "🎁",
        text: `${p.gifter_name} gave the family a year of FutureRoots Premium ♥`,
      };
    case "prediction_added":
      return {
        icon: "🔮",
        text: `${e.actor_name} shared a prediction for ${p.child_name}'s future`,
      };
    case "predictions_sealed":
      return {
        icon: "📜",
        text: `This year's predictions for ${p.child_name} are sealed away until their 18th birthday`,
      };
    case "predictions_released":
      return {
        icon: "📖",
        text: `${p.child_name}'s Book of Predictions is open. Years of family wishes to read together.`,
      };
    default:
      return { icon: "✨", text: String(p.title ?? e.type) };
  }
}
