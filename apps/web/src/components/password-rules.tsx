"use client";

/* Live checklist mirroring the API's complexity rules (app/security.py). */

const RULES: { label: string; test: (p: string) => boolean }[] = [
  { label: "At least 8 characters", test: (p) => p.length >= 8 },
  { label: "An uppercase letter", test: (p) => /[A-Z]/.test(p) },
  { label: "A lowercase letter", test: (p) => /[a-z]/.test(p) },
  { label: "A number", test: (p) => /[0-9]/.test(p) },
  { label: "A symbol (like ! or #)", test: (p) => /[^A-Za-z0-9]/.test(p) },
];

export function passwordMeetsRules(password: string): boolean {
  return RULES.every((r) => r.test(password));
}

export function PasswordRules({ password }: { password: string }) {
  return (
    <ul className="mt-2 space-y-1" aria-live="polite">
      {RULES.map((rule) => {
        const ok = rule.test(password);
        return (
          <li
            key={rule.label}
            className={`flex items-center gap-2 text-xs transition-colors ${
              ok ? "text-emerald-700" : "text-stone-400"
            }`}
          >
            <span
              className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold ${
                ok ? "bg-emerald-100 text-emerald-700" : "bg-stone-100 text-stone-400"
              }`}
              aria-hidden
            >
              {ok ? "✓" : "○"}
            </span>
            {rule.label}
          </li>
        );
      })}
    </ul>
  );
}
