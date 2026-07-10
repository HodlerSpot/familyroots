"use client";

import { forwardRef } from "react";

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
