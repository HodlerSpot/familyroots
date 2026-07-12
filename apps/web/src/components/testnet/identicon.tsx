"use client";

// Deterministic identicon: a wallet-seeded SVG avatar so every tester has a
// distinct picture with no upload. Same seed always renders the same art (no
// Math.random). Testnet-only; imported alongside the rest of the harness.

// Brand-adjacent palette (greens/blues/teals from the FutureRoots family).
const PALETTE = [
  "#1FA84D",
  "#1E4FD8",
  "#0EA5A3",
  "#059669",
  "#2563EB",
  "#0891B2",
  "#0D9488",
  "#4F46E5",
];

// FNV-1a: a small, stable string hash.
function hashSeed(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

// Deterministic PRNG (mulberry32) seeded from the hash: a repeatable stream
// of values, so the picture is fixed per seed.
function mulberry32(seed: number): () => number {
  let a = seed;
  return () => {
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function Identicon({ seed, size }: { seed: string; size: number }) {
  const h = hashSeed(seed.toLowerCase());
  const rand = mulberry32(h);
  const c1 = PALETTE[Math.floor(rand() * PALETTE.length)];
  let c2 = PALETTE[Math.floor(rand() * PALETTE.length)];
  if (c2 === c1) c2 = PALETTE[(PALETTE.indexOf(c1) + 3) % PALETTE.length];

  // A 5x5 grid, mirrored left-to-right for a pleasing symmetric glyph: only
  // the left three columns are decided, columns 4 and 5 reflect them.
  const filled: boolean[] = [];
  for (let i = 0; i < 15; i++) filled.push(rand() > 0.5);

  const cell = size / 5;
  const gid = `fr-ig-${h.toString(36)}`;
  const rects: React.ReactNode[] = [];
  for (let row = 0; row < 5; row++) {
    for (let col = 0; col < 5; col++) {
      const srcCol = col < 3 ? col : 4 - col;
      if (filled[row * 3 + srcCol]) {
        rects.push(
          <rect
            key={`${row}-${col}`}
            x={col * cell}
            y={row * cell}
            width={cell + 0.6}
            height={cell + 0.6}
            fill={`url(#${gid})`}
          />
        );
      }
    }
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Tester avatar"
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor={c1} />
          <stop offset="100%" stopColor={c2} />
        </linearGradient>
      </defs>
      <rect x={0} y={0} width={size} height={size} fill="#f5f5f4" />
      {rects}
    </svg>
  );
}

// Avatar: an X profile picture when one is connected, otherwise the wallet
// identicon. Always round and sized by the `size` prop.
export function Avatar({
  seed,
  src,
  size = 40,
  alt = "",
}: {
  seed: string;
  src?: string | null;
  size?: number;
  alt?: string;
}) {
  const style = { width: size, height: size };
  if (src) {
    return (
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={src}
        alt={alt}
        style={style}
        className="shrink-0 rounded-full bg-stone-100 object-cover"
      />
    );
  }
  return (
    <span
      style={style}
      className="inline-block shrink-0 overflow-hidden rounded-full bg-stone-100"
    >
      <Identicon seed={seed} size={size} />
    </span>
  );
}
