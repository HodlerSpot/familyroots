"use client";

import { FeedEventOut, mediaUrl } from "@/lib/api";
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
    default:
      return { icon: "✨", text: p.title ?? e.type };
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
              {e.payload.media_id && (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={mediaUrl(e.payload.media_id)}
                  alt={e.payload.title ?? "family memory"}
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
