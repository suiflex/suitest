import { Link } from "@tanstack/react-router";
import type React from "react";

export function AuthContainer({ children }: { children: React.ReactNode }): React.ReactElement {
  return <section className="mx-auto max-w-md space-y-6 pt-16">{children}</section>;
}

export function AuthHeader({ subtitle }: { subtitle?: React.ReactNode }): React.ReactElement {
  return (
    <div className="space-y-3 text-center">
      <img src="/logo.svg" alt="Suitest" className="mx-auto h-12 w-12 rounded-xl" />
      <h2 className="font-mono text-2xl font-semibold tracking-tight">
        sui<span className="text-accent">test</span>
      </h2>
      {subtitle ? <p className="text-[13px] text-fg-3">{subtitle}</p> : null}
    </div>
  );
}

export function AuthForm({
  onSubmit,
  children,
}: {
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void | Promise<void>;
  children: React.ReactNode;
}): React.ReactElement {
  return (
    <form
      onSubmit={(e) => {
        void onSubmit(e);
      }}
      className="space-y-4 rounded-lg border border-border bg-elev-1 p-5 text-left"
    >
      {children}
    </form>
  );
}

export function AuthErrorAlert({ error }: { error: string | null }): React.ReactElement | null {
  if (!error) return null;
  return (
    <p
      role="alert"
      className="rounded-md border border-red/30 bg-red/10 px-3 py-2 text-[12.5px] text-red"
    >
      {error}
    </p>
  );
}

export function AuthSubmitButton({
  submitting,
  label,
  loadingLabel,
}: {
  submitting: boolean;
  label: string;
  loadingLabel: string;
}): React.ReactElement {
  return (
    <button
      type="submit"
      disabled={submitting}
      className="inline-flex w-full items-center justify-center rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-accent-fg hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {submitting ? loadingLabel : label}
    </button>
  );
}

export function AuthPasswordInput({
  id,
  name,
  label,
  value,
  onChange,
  autoComplete = "new-password",
  required = true,
  minLength = 8,
}: {
  id: string;
  name: string;
  label: string;
  value: string;
  onChange: (val: string) => void;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
}): React.ReactElement {
  return (
    <div className="space-y-2">
      <label htmlFor={id} className="text-[12.5px] font-medium text-fg-1">
        {label}
      </label>
      <input
        id={id}
        name={name}
        type="password"
        autoComplete={autoComplete}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        required={required}
        minLength={minLength}
        className="w-full rounded-md border border-border bg-bg-base px-3 py-2 text-[13px] text-fg-1 outline-none placeholder:text-fg-5 focus:border-accent"
      />
    </div>
  );
}

export function AuthBackToLogin({ label }: { label?: string }): React.ReactElement {
  return (
    <div className="pt-2 text-center">
      <Link
        to="/login"
        className="text-[12.5px] text-fg-3 hover:text-accent transition-colors"
      >
        {label ?? "Back to sign in"}
      </Link>
    </div>
  );
}

export function AuthSuccessCard({
  title,
  description,
  titleTestId,
  descTestId,
  actionLabel,
  actionTo = "/login",
}: {
  title: string;
  description: string;
  titleTestId?: string;
  descTestId?: string;
  actionLabel: string;
  actionTo?: string;
}): React.ReactElement {
  return (
    <div className="space-y-4 rounded-lg border border-border bg-elev-1 p-6 text-center">
      <div className="space-y-2">
        <h3 className="text-[15px] font-semibold text-fg-1" data-testid={titleTestId}>
          {title}
        </h3>
        <p className="text-[13px] text-fg-3" data-testid={descTestId}>
          {description}
        </p>
      </div>
      <Link
        to={actionTo}
        className="inline-flex items-center justify-center rounded-md bg-accent px-4 py-2 text-[13px] font-medium text-accent-fg hover:opacity-90"
      >
        {actionLabel}
      </Link>
    </div>
  );
}

export function AuthFooter(): React.ReactElement {
  return (
    <p className="pt-4 text-center text-[11px] text-fg-5">
      © 2026 Suitest contributors · Apache-2.0 · open source
    </p>
  );
}
