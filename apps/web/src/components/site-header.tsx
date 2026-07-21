"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { api, getToken, mediaUrl, setToken, UserOut } from "@/lib/api";
import { startIdleWatch } from "@/lib/idle";
import { Logo } from "@/components/logo";
import { NotificationBell } from "@/components/notification-bell";
import { QuestBoard, testnetApi } from "@/components/testnet/api";
import { Avatar } from "@/components/testnet/identicon";

const IS_TESTNET = process.env.NEXT_PUBLIC_TESTNET === "1";

function shortWallet(addr: string): string {
  return `${addr.slice(0, 6)}…${addr.slice(-4)}`;
}

export function SiteHeader() {
  const pathname = usePathname();
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    setAuthed(!!getToken());
  }, [pathname]);

  // Idle logout for default (non-remembered) sessions. Re-armed on navigation;
  // a no-op in testnet and for remembered sessions.
  useEffect(() => {
    if (IS_TESTNET) return;
    return startIdleWatch();
  }, [pathname]);

  // The landing page opens with the full hero lockup — no header needed there
  if (pathname === "/") return null;

  return (
    <header className="border-b border-stone-200 bg-white">
      <div className="mx-auto flex max-w-3xl items-center justify-between gap-4 px-6 py-3">
        <a href="/" aria-label="FutureRoots home">
          <Logo size="sm" />
        </a>
        {authed ? (
          <div className="flex items-center gap-1">
            {/* The bell is a family-product concept; testnet has no inbox. */}
            {!IS_TESTNET && <NotificationBell />}
            <AccountMenu />
          </div>
        ) : (
          <span className="hidden text-sm text-stone-500 sm:block">
            Building Generational Wealth &amp; Memories
          </span>
        )}
      </div>
    </header>
  );
}

type MenuLink = { label: string; href: string; icon: ReactNode };

// Module-level cache so the avatar is present on the very first render of any
// (re)mount — no null -> data flash as you move between pages.
let cachedMe: UserOut | null = null;
let cachedBoard: QuestBoard | null = null;
let cachedIsAdmin = false;

// Top-level (stable identity) so re-renders reconcile the same <img> instead of
// remounting it — remounting was reloading the avatar and causing the flicker.
function AvatarNode({
  px,
  me,
  board,
}: {
  px: 36 | 40;
  me: UserOut | null;
  board: QuestBoard | null;
}) {
  const box = px === 36 ? "h-9 w-9" : "h-10 w-10";
  const txt = px === 36 ? "text-sm" : "text-base";
  if (IS_TESTNET) {
    return <Avatar seed={board?.wallet_address ?? ""} src={board?.avatar_url} size={px} />;
  }
  if (me?.avatar_media_id) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={mediaUrl(me.avatar_media_id)}
        alt=""
        className={`${box} rounded-full object-cover`}
      />
    );
  }
  const letter = (me?.display_name ?? "?").charAt(0).toUpperCase();
  return (
    <span
      className={`${box} ${txt} flex items-center justify-center rounded-full bg-emerald-100 font-semibold text-emerald-800`}
    >
      {letter}
    </span>
  );
}

function AccountMenu() {
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const [visible, setVisible] = useState(false);
  const [me, setMe] = useState<UserOut | null>(cachedMe); // family product
  const [board, setBoard] = useState<QuestBoard | null>(cachedBoard); // testnet
  const [isAdmin, setIsAdmin] = useState(cachedIsAdmin);

  const triggerRef = useRef<HTMLButtonElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const itemRefs = useRef<(HTMLElement | null)[]>([]);

  // One profile fetch for the whole menu. In testnet we read the board for the
  // name/avatar, and separately probe the family /me only to learn whether this
  // person is an operator (the board carries no role); either failure is fine.
  useEffect(() => {
    if (IS_TESTNET) {
      testnetApi
        .quests()
        .then((b) => {
          cachedBoard = b;
          setBoard(b);
        })
        .catch(() => {});
      api
        .me()
        .then((u) => {
          cachedIsAdmin = u.role === "admin";
          setIsAdmin(cachedIsAdmin);
        })
        .catch(() => {});
    } else {
      api
        .me()
        .then((u) => {
          cachedMe = u;
          cachedIsAdmin = u.role === "admin";
          setMe(u);
          setIsAdmin(cachedIsAdmin);
        })
        .catch(() => {});
    }
  }, []);

  const close = useCallback((returnFocus: boolean) => {
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }, []);

  // Close whenever the route changes (a menu item was followed, etc.)
  useEffect(() => {
    setOpen(false);
  }, [pathname]);

  // Fade + scale in, and land focus on the first item once it has mounted.
  useEffect(() => {
    if (!open) {
      setVisible(false);
      return;
    }
    const raf = requestAnimationFrame(() => {
      setVisible(true);
      itemRefs.current[0]?.focus();
    });
    return () => cancelAnimationFrame(raf);
  }, [open]);

  // Outside pointerdown closes. We refocus the trigger first; if the click
  // landed on a focusable target the browser hands focus there next, otherwise
  // focus stays on the trigger (matching Esc behavior).
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        close(true);
      }
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open, close]);

  const links: MenuLink[] = IS_TESTNET
    ? [
        { label: "My account", href: "/account", icon: <UserIcon /> },
        { label: "Leaderboard", href: "/leaderboard", icon: <TrophyIcon /> },
        ...(isAdmin
          ? [{ label: "Command center", href: "/admin", icon: <GridIcon /> }]
          : []),
      ]
    : [
        { label: "My profile", href: "/account", icon: <UserIcon /> },
        { label: "My contributions", href: "/contributions", icon: <GiftIcon /> },
        { label: "Notification settings", href: "/settings", icon: <BellIcon /> },
        ...(isAdmin
          ? [{ label: "Command center", href: "/admin", icon: <GridIcon /> }]
          : []),
      ];

  const name = IS_TESTNET
    ? board
      ? board.x_username || board.display_name || shortWallet(board.wallet_address)
      : ""
    : me?.display_name ?? "";
  const secondary = IS_TESTNET
    ? board
      ? shortWallet(board.wallet_address)
      : ""
    : me?.email ?? "";

  function signOut() {
    setOpen(false);
    cachedMe = null;
    cachedBoard = null;
    cachedIsAdmin = false;
    setToken(null);
    router.replace("/login");
  }

  function onMenuKeyDown(e: React.KeyboardEvent) {
    const els = itemRefs.current.filter((el): el is HTMLElement => !!el);
    if (els.length === 0) return;
    const idx = els.indexOf(document.activeElement as HTMLElement);
    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        els[(idx + 1) % els.length]?.focus();
        break;
      case "ArrowUp":
        e.preventDefault();
        els[(idx - 1 + els.length) % els.length]?.focus();
        break;
      case "Home":
        e.preventDefault();
        els[0]?.focus();
        break;
      case "End":
        e.preventDefault();
        els[els.length - 1]?.focus();
        break;
      case "Escape":
        e.preventDefault();
        close(true);
        break;
      case "Tab":
        // Let focus leave the menu, and close behind it.
        close(false);
        break;
      case " ":
        // Space activates links (buttons already do this natively).
        if (document.activeElement instanceof HTMLAnchorElement) {
          e.preventDefault();
          document.activeElement.click();
        }
        break;
    }
  }

  return (
    <div ref={wrapRef} className="relative">
      <button
        ref={triggerRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls="account-menu"
        aria-label={`Account menu for ${name || "your account"}`}
        onClick={() => (open ? close(false) : setOpen(true))}
        className={`flex items-center justify-center rounded-full p-1 transition-shadow focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald-500 focus-visible:ring-offset-2 ${
          open
            ? "ring-2 ring-emerald-600"
            : "ring-1 ring-stone-200 hover:ring-emerald-300"
        }`}
      >
        <AvatarNode px={36} me={me} board={board} />
      </button>

      {open && (
        <div
          id="account-menu"
          role="menu"
          aria-label="Account"
          onKeyDown={onMenuKeyDown}
          className={`absolute right-0 top-[calc(100%+8px)] z-50 w-[min(16rem,calc(100vw-1.5rem))] origin-top-right rounded-2xl border border-stone-200 bg-white p-1.5 shadow-lg motion-safe:transition motion-safe:duration-[120ms] ${
            visible ? "scale-100 opacity-100" : "scale-95 opacity-0"
          }`}
        >
          <div className="flex items-center gap-3 px-3 py-2.5">
            <AvatarNode px={40} me={me} board={board} />
            <div className="min-w-0">
              <p className="truncate text-sm font-semibold text-emerald-900">{name}</p>
              <p
                className={`truncate text-xs text-stone-500 ${
                  IS_TESTNET ? "font-mono" : ""
                }`}
              >
                {secondary}
              </p>
            </div>
          </div>

          <div role="separator" className="mx-1 my-1.5 h-px bg-stone-100" />

          {links.map((link, i) => {
            const active = pathname === link.href;
            return (
              <a
                key={link.href}
                ref={(el) => {
                  itemRefs.current[i] = el;
                }}
                href={link.href}
                role="menuitem"
                tabIndex={-1}
                onClick={() => close(false)}
                className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-base font-medium hover:bg-emerald-50 ${
                  active ? "bg-emerald-50 font-semibold text-emerald-900" : "text-stone-800"
                }`}
              >
                <span className={active ? "text-emerald-700" : "text-stone-500"}>
                  {link.icon}
                </span>
                {link.label}
              </a>
            );
          })}

          <div role="separator" className="mx-1 my-1.5 h-px bg-stone-100" />

          <button
            ref={(el) => {
              itemRefs.current[links.length] = el;
            }}
            type="button"
            role="menuitem"
            tabIndex={-1}
            onClick={signOut}
            className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-base font-medium text-red-700 hover:bg-red-50"
          >
            <span className="text-red-600">
              <PowerIcon />
            </span>
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

// --- 18px line icons (stroke = currentColor so they inherit the row tint) ---

const iconProps = {
  width: 18,
  height: 18,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.75,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

function UserIcon() {
  return (
    <svg {...iconProps}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-3.3 3.6-6 8-6s8 2.7 8 6" />
    </svg>
  );
}

function GiftIcon() {
  return (
    <svg {...iconProps}>
      <path d="M20 12v9H4v-9" />
      <path d="M2 7h20v5H2z" />
      <path d="M12 22V7" />
      <path d="M12 7S11 3 8.5 3 6 5 6 5.5 7 7 12 7Z" />
      <path d="M12 7s1-4 3.5-4S18 5 18 5.5 17 7 12 7Z" />
    </svg>
  );
}

function BellIcon() {
  return (
    <svg {...iconProps}>
      <path d="M18 8a6 6 0 0 0-12 0c0 7-3 9-3 9h18s-3-2-3-9" />
      <path d="M10.3 21a1.94 1.94 0 0 0 3.4 0" />
    </svg>
  );
}

function TrophyIcon() {
  return (
    <svg {...iconProps}>
      <path d="M8 21h8" />
      <path d="M12 17v4" />
      <path d="M7 4h10v5a5 5 0 0 1-10 0z" />
      <path d="M7 5H4v2a3 3 0 0 0 3 3" />
      <path d="M17 5h3v2a3 3 0 0 1-3 3" />
    </svg>
  );
}

function GridIcon() {
  return (
    <svg {...iconProps}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="7" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
      <rect x="14" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function PowerIcon() {
  return (
    <svg {...iconProps}>
      <path d="M12 2v10" />
      <path d="M18.4 6.6a9 9 0 1 1-12.8 0" />
    </svg>
  );
}
