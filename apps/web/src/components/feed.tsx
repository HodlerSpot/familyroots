"use client";

import { FeedEventOut, formatMoney, mediaUrl } from "@/lib/api";
import { Card } from "@/components/ui";

function timeAgo(iso: string): string {
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

function eventLine(e: FeedEventOut): { icon: string; text: string } {
  const p = e.payload;
  switch (e.type) {
    case "milestone":
      return { icon: "🎉", text: `${p.child_name}: ${p.title}` };
    case "memory_added":
      return {
        icon: p.item_type === "photo" ? "📷" : p.item_type === "message" ? "💬" : "📎",
        text: `${e.actor_name} added a memory for ${p.child_name}: "${p.title}"`,
      };
    case "member_joined":
      return { icon: "🌱", text: `${p.member_name} joined the family as a ${p.role}` };
    case "achievement":
      return { icon: "🏅", text: `${p.child_name} reached a goal: ${p.title}` };
    case "capsule_created":
      return {
        icon: "✉️",
        text: `${p.created_by_name} sealed a time capsule for ${p.child_name}`,
      };
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
    default:
      return { icon: "✨", text: String(p.title ?? e.type) };
  }
}

export function FamilyFeedList({ events }: { events: FeedEventOut[] }) {
  if (events.length === 0) {
    return (
      <p className="text-stone-600">
        Nothing here yet — add a child, share a memory, or celebrate a milestone and it
        will show up for the whole family.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {events.map((e) => {
        const { icon, text } = eventLine(e);
        return (
          <Card key={e.id} className="flex items-start gap-4">
            <span className="text-2xl">{icon}</span>
            <div className="min-w-0 flex-1">
              <p className="text-stone-900">{text}</p>
              {e.type === "milestone" && e.payload.description && (
                <p className="mt-1 text-sm text-stone-600">{e.payload.description}</p>
              )}
              {e.type === "contribution" && e.payload.message && (
                <p className="mt-1 text-sm italic text-stone-600">“{e.payload.message}”</p>
              )}
              {(e.type === "milestone" || e.type === "achievement") && e.child_id && (
                <a
                  href={`${location.pathname.replace(/\/$/, "")}/child/${e.child_id}/contribute`}
                  className="mt-2 inline-block rounded-lg bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-900 hover:bg-emerald-100"
                >
                  💝 Celebrate with a gift
                </a>
              )}
              {e.payload.media_id && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(String(e.payload.media_id))}
                  alt={String(e.payload.title ?? "family memory")}
                  className="mt-3 max-h-72 rounded-xl object-cover"
                />
              )}
              <p className="mt-1 text-xs text-stone-400">{timeAgo(e.created_at)}</p>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
