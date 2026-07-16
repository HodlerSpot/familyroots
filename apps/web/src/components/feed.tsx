"use client";

import { useState } from "react";
import {
  api,
  ApiError,
  CommentOut,
  FeedEventOut,
  formatMoney,
  mediaUrl,
  REACTION_EMOJI,
  ReactionSummary,
} from "@/lib/api";
import { Button, Card, ErrorNote, Input, ZoomableImage } from "@/components/ui";
import { familyPhrase } from "@/lib/text";

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
    // Copy from docs/brand/premium-copy.md §4. No amounts on the feed:
    // "a year of Premium" is the unit of love.
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
    default:
      return { icon: "✨", text: String(p.title ?? e.type) };
  }
}

/** The warm little row of emoji buttons shown under a moment or comment. */
function ReactionBar({
  reactions,
  onToggle,
  size = "md",
}: {
  reactions: ReactionSummary[];
  onToggle: (emoji: string) => void;
  size?: "md" | "sm";
}) {
  const byEmoji = new Map(reactions.map((r) => [r.emoji, r]));
  const pad = size === "sm" ? "px-1.5 py-0.5 text-xs" : "px-2 py-1 text-sm";
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      {REACTION_EMOJI.map((emoji) => {
        const summary = byEmoji.get(emoji);
        const count = summary?.count ?? 0;
        const reacted = summary?.reacted ?? false;
        return (
          <button
            key={emoji}
            type="button"
            onClick={() => onToggle(emoji)}
            aria-pressed={reacted}
            className={`inline-flex items-center gap-1 rounded-full border transition ${pad} ${
              reacted
                ? "border-emerald-300 bg-emerald-50 text-emerald-900 ring-1 ring-emerald-200"
                : "border-stone-200 bg-white text-stone-600 hover:border-emerald-300 hover:bg-emerald-50"
            }`}
          >
            <span>{emoji}</span>
            {count > 0 && <span className="font-medium tabular-nums">{count}</span>}
          </button>
        );
      })}
    </div>
  );
}

function CommentRow({
  comment,
  onChanged,
  onDeleted,
}: {
  comment: CommentOut;
  onChanged: (updated: CommentOut) => void;
  onDeleted: (id: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function toggle(emoji: string) {
    try {
      const { reactions } = await api.toggleReaction("comment", comment.id, emoji);
      onChanged({ ...comment, reactions });
    } catch {
      // a failed reaction shouldn't break the thread; leave state as-is
    }
  }

  async function remove() {
    setBusy(true);
    try {
      await api.deleteComment(comment.id);
      onDeleted(comment.id);
    } catch {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-xl bg-stone-50 px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-sm font-semibold text-stone-900">{comment.author_name}</span>
        <span className="shrink-0 text-xs text-stone-400">{timeAgo(comment.created_at)}</span>
      </div>
      <p className="mt-0.5 whitespace-pre-wrap text-sm text-stone-700">{comment.body}</p>
      <div className="mt-2 flex items-center justify-between gap-2">
        <ReactionBar reactions={comment.reactions} onToggle={toggle} size="sm" />
        {comment.can_delete && (
          <button
            type="button"
            onClick={remove}
            disabled={busy}
            className="shrink-0 text-xs text-stone-400 hover:text-red-600 disabled:opacity-50"
          >
            Delete
          </button>
        )}
      </div>
    </div>
  );
}

function MomentCard({ event }: { event: FeedEventOut }) {
  const { icon, text } = eventLine(event);
  const [reactions, setReactions] = useState<ReactionSummary[]>(event.reactions);
  const [commentCount, setCommentCount] = useState(event.comment_count);
  const [expanded, setExpanded] = useState(false);
  const [comments, setComments] = useState<CommentOut[] | null>(null);
  const [loadingComments, setLoadingComments] = useState(false);
  const [draft, setDraft] = useState("");
  const [posting, setPosting] = useState(false);
  const [error, setError] = useState("");

  async function toggleMomentReaction(emoji: string) {
    try {
      const res = await api.toggleReaction("feed_event", event.id, emoji);
      setReactions(res.reactions);
    } catch {
      // ignore; keep current reactions
    }
  }

  async function toggleThread() {
    const next = !expanded;
    setExpanded(next);
    if (next && comments === null && !loadingComments) {
      setLoadingComments(true);
      try {
        setComments(await api.listComments(event.id));
      } catch (err) {
        setError(err instanceof ApiError ? err.message : "Couldn't load comments");
      } finally {
        setLoadingComments(false);
      }
    }
  }

  async function submitComment(e: React.FormEvent) {
    e.preventDefault();
    const body = draft.trim();
    if (!body) return;
    setPosting(true);
    setError("");
    try {
      const created = await api.addComment(event.id, body);
      setComments((prev) => [...(prev ?? []), created]);
      setCommentCount((c) => c + 1);
      setDraft("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't post your comment");
    } finally {
      setPosting(false);
    }
  }

  function onCommentChanged(updated: CommentOut) {
    setComments((prev) => prev?.map((c) => (c.id === updated.id ? updated : c)) ?? prev);
  }

  function onCommentDeleted(id: string) {
    setComments((prev) => prev?.filter((c) => c.id !== id) ?? prev);
    setCommentCount((c) => Math.max(0, c - 1));
  }

  return (
    <Card className="flex items-start gap-4">
      <span className="text-2xl">{icon}</span>
      <div className="min-w-0 flex-1">
        <p className="text-stone-900">{text}</p>
        {event.type === "milestone" && event.payload.description && (
          <p className="mt-1 text-sm text-stone-600">{event.payload.description}</p>
        )}
        {(event.type === "contribution" || event.type === "premium_gifted") &&
          event.payload.message && (
            <p className="mt-1 text-sm italic text-stone-600">“{event.payload.message}”</p>
          )}
        {(event.type === "milestone" || event.type === "achievement") && event.child_id && (
          <a
            href={`${location.pathname.replace(/\/$/, "")}/child/${event.child_id}/contribute`}
            className="mt-2 inline-block rounded-lg bg-emerald-50 px-3 py-1.5 text-sm font-medium text-emerald-900 hover:bg-emerald-100"
          >
            💝 Celebrate with a gift
          </a>
        )}
        {event.payload.media_id &&
          (String(event.payload.media_content_type ?? "").startsWith("video/") ||
          event.payload.item_type === "video" ? (
            <video
              controls
              src={mediaUrl(String(event.payload.media_id))}
              className="mt-3 max-h-72 w-full rounded-xl"
            />
          ) : (
            <ZoomableImage
              src={mediaUrl(String(event.payload.media_id))}
              alt={String(event.payload.title ?? "family memory")}
              className="mt-3 max-h-72 rounded-xl object-cover"
            />
          ))}
        <p className="mt-1 text-xs text-stone-400">{timeAgo(event.created_at)}</p>

        <div className="mt-3 flex flex-wrap items-center gap-3">
          <ReactionBar reactions={reactions} onToggle={toggleMomentReaction} />
          <button
            type="button"
            onClick={toggleThread}
            aria-expanded={expanded}
            className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-sm transition ${
              expanded
                ? "border-emerald-300 bg-emerald-50 text-emerald-900"
                : "border-stone-200 bg-white text-stone-600 hover:border-emerald-300 hover:bg-emerald-50"
            }`}
          >
            💬 {commentCount}
          </button>
        </div>

        {expanded && (
          <div className="mt-3 space-y-3">
            {loadingComments && <p className="text-sm text-stone-500">Loading…</p>}
            {comments?.map((c) => (
              <CommentRow
                key={c.id}
                comment={c}
                onChanged={onCommentChanged}
                onDeleted={onCommentDeleted}
              />
            ))}
            {!loadingComments && comments?.length === 0 && (
              <p className="text-sm text-stone-500">Be the first to say something kind.</p>
            )}
            <form onSubmit={submitComment} className="flex items-center gap-2">
              <Input
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Add a comment…"
                aria-label="Add a comment"
              />
              <Button type="submit" variant="soft" disabled={posting || !draft.trim()}>
                {posting ? "…" : "Comment"}
              </Button>
            </form>
            <ErrorNote>{error}</ErrorNote>
          </div>
        )}
      </div>
    </Card>
  );
}

export function FamilyFeedList({ events }: { events: FeedEventOut[] }) {
  if (events.length === 0) {
    return (
      <p className="text-stone-600">
        Nothing here yet. Add a child, share a memory, or celebrate a milestone and it
        will show up for the whole family.
      </p>
    );
  }
  return (
    <div className="space-y-3">
      {events.map((e) => (
        <MomentCard key={e.id} event={e} />
      ))}
    </div>
  );
}
