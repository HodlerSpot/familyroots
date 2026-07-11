/* Subtle full-page backdrop: pixel clusters dissolving from the corners,
   echoing the logo's pixelating-shield motif. Deterministic layout (no
   Math.random) so server and client render identically. */

// greens doubled up: they wash out faster than blue at low opacity
const PALETTE = ["#1FA84D", "#15803D", "#2A66DD", "#1E4FD8"];
const COLS = 9;
const ROWS = 7;
const CELL = 30;

function cluster(align: "tr" | "bl") {
  const squares: React.ReactNode[] = [];
  for (let r = 0; r < ROWS; r++) {
    for (let c = 0; c < COLS; c++) {
      const h = ((r * 31 + c * 17 + 7) * 2654435761) % 100;
      if (h < 55) continue; // sparse scatter
      // strongest at the top-right of the cluster, fading away from it
      const factor = ((c + 1) / COLS) * ((ROWS - r) / ROWS);
      if (factor < 0.08) continue;
      const size = 9 + (h % 3) * 4;
      const color = PALETTE[h % 4];
      const isGreen = h % 4 < 2;
      squares.push(
        <rect
          key={`${align}-${r}-${c}`}
          x={c * CELL + (h % 5)}
          y={r * CELL + (h % 4)}
          width={size}
          height={size}
          rx={1.5}
          fill={color}
          opacity={(0.05 + 0.1 * factor) * (isGreen ? 1.25 : 1)}
        />
      );
    }
  }
  return squares;
}

export function PixelBackdrop() {
  const width = COLS * CELL;
  const height = ROWS * CELL;
  return (
    <div aria-hidden className="pointer-events-none fixed inset-0 -z-10 overflow-hidden">
      <svg
        width={width}
        height={height}
        className="absolute right-0 top-0"
        viewBox={`0 0 ${width} ${height}`}
      >
        {cluster("tr")}
      </svg>
      <svg
        width={width}
        height={height}
        className="absolute bottom-0 left-0 rotate-180"
        viewBox={`0 0 ${width} ${height}`}
      >
        {cluster("bl")}
      </svg>
    </div>
  );
}
