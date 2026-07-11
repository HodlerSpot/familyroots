/* Brand lockup: shield mark (public/logo-mark.png) + two-tone wordmark.
   Source artwork: docs/brand/FutureRootsLogo.jpg */

const SIZES = {
  sm: { img: "h-9", text: "text-2xl", tagline: "hidden" },
  md: { img: "h-12", text: "text-3xl", tagline: "text-xs" },
  lg: { img: "h-20", text: "text-5xl", tagline: "text-sm" },
} as const;

export function Logo({
  size = "sm",
  withTagline = false,
  className = "",
}: {
  size?: keyof typeof SIZES;
  withTagline?: boolean;
  className?: string;
}) {
  const s = SIZES[size];
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src="/logo-mark.png" alt="" className={`${s.img} w-auto`} />
      <span className="flex flex-col leading-none">
        <span className={`font-extrabold tracking-tight ${s.text}`}>
          <span className="text-[#1FA84D]">Future</span>
          <span className="text-[#1E4FD8]">Roots</span>
        </span>
        {withTagline && (
          <span className={`mt-1.5 font-medium tracking-wide text-stone-500 ${s.tagline}`}>
            Building Generational Wealth &amp; Memories
          </span>
        )}
      </span>
    </span>
  );
}
