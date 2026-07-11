"use client";

import { forwardRef, useState } from "react";

/* Minimal warm-styled primitives for the Phase 1 scaffold.
   These get replaced by ShadCN components when the design system lands. */

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "soft" }
>(function Button({ className = "", variant = "primary", ...props }, ref) {
  const styles =
    variant === "primary"
      ? "bg-emerald-700 text-white hover:bg-emerald-800"
      : "bg-emerald-50 text-emerald-900 hover:bg-emerald-100";
  return (
    <button
      ref={ref}
      className={`rounded-lg px-5 py-3 text-base font-semibold transition-colors disabled:opacity-50 ${styles} ${className}`}
      {...props}
    />
  );
});

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className = "", ...props }, ref) {
    return (
      <input
        ref={ref}
        className={`w-full rounded-lg border border-stone-300 bg-white px-4 py-3 text-base text-stone-900 placeholder-stone-400 focus:border-emerald-600 focus:outline-none ${className}`}
        {...props}
      />
    );
  }
);

export function PasswordInput({
  className = "",
  ...props
}: Omit<React.InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input {...props} type={visible ? "text" : "password"} className={`pr-12 ${className}`} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        className="absolute right-3 top-1/2 -translate-y-1/2 p-1 text-stone-400 transition-colors hover:text-stone-600"
      >
        {visible ? (
          // eye-off
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
            <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
            <path d="M14.12 14.12a3 3 0 1 1-4.24-4.24" />
            <line x1="1" y1="1" x2="23" y2="23" />
          </svg>
        ) : (
          // eye
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
            <circle cx="12" cy="12" r="3" />
          </svg>
        )}
      </button>
    </div>
  );
}

export function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`rounded-2xl border border-stone-200 bg-white p-6 shadow-sm ${className}`}>
      {children}
    </div>
  );
}

export function Label({ children, htmlFor }: { children: React.ReactNode; htmlFor?: string }) {
  return (
    <label htmlFor={htmlFor} className="mb-1 block text-sm font-medium text-stone-700">
      {children}
    </label>
  );
}

export function ErrorNote({ children }: { children: React.ReactNode }) {
  if (!children) return null;
  return <p className="rounded-lg bg-red-50 px-4 py-2 text-sm text-red-800">{children}</p>;
}
