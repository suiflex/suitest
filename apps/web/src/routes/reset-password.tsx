import { createFileRoute, Link } from "@tanstack/react-router";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import {
  AuthBackToLogin,
  AuthContainer,
  AuthErrorAlert,
  AuthFooter,
  AuthForm,
  AuthHeader,
  AuthPasswordInput,
  AuthSubmitButton,
  AuthSuccessCard,
} from "@/components/shared/AuthLayout";

interface ResetPasswordSearch {
  token?: string;
}

export function ResetPassword(): React.ReactElement {
  const { t } = useTranslation();
  const search = Route.useSearch();
  const token = search.token?.trim() ?? "";

  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent<HTMLFormElement>): Promise<void> => {
    event.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError(
        t("auth.passwordTooShort", "Password must be at least 8 characters."),
      );
      return;
    }

    if (password !== confirmPassword) {
      setError(t("auth.passwordsDoNotMatch", "Passwords do not match."));
      return;
    }

    setSubmitting(true);

    try {
      const res = await fetch("/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password }),
      });

      if (!res.ok) {
        if (res.status === 400) {
          throw new Error("bad_token");
        }
        throw new Error("reset_failed");
      }

      setSubmitted(true);
    } catch (err) {
      if (err instanceof Error && err.message === "bad_token") {
        setError(
          t(
            "auth.resetTokenInvalid",
            "This reset link is invalid or has expired.",
          ),
        );
      } else {
        setError(
          t(
            "auth.resetGenericError",
            "Could not reset your password. Please try requesting a new link.",
          ),
        );
      }
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <AuthContainer>
      <AuthHeader
        subtitle={t(
          "auth.resetPasswordDesc",
          "Please choose a secure password with at least 8 characters.",
        )}
      />

      {!token ? (
        <div className="space-y-4 rounded-lg border border-red/30 bg-red/10 p-6 text-center">
          <p className="text-[13px] text-red font-medium" data-testid="missing-token-warning">
            {t("auth.missingToken", "Invalid or missing reset token.")}
          </p>
          <Link
            to="/login"
            className="inline-flex items-center justify-center rounded-md border border-border bg-elev-1 px-4 py-2 text-[13px] font-medium text-fg-1 hover:bg-elev-2"
          >
            {t("auth.backToLogin", "Back to sign in")}
          </Link>
        </div>
      ) : submitted ? (
        <AuthSuccessCard
          title={t("auth.resetPasswordSuccessTitle", "Password updated")}
          description={t(
            "auth.resetPasswordSuccessDesc",
            "Your password has been reset successfully. You can now sign in.",
          )}
          titleTestId="reset-password-success-title"
          descTestId="reset-password-success-desc"
          actionLabel={t("auth.backToLogin", "Back to sign in")}
        />
      ) : (
        <AuthForm onSubmit={onSubmit}>
          <AuthPasswordInput
            id="new-password"
            name="newPassword"
            label={t("auth.newPasswordLabel", "New password")}
            value={password}
            onChange={setPassword}
          />

          <AuthPasswordInput
            id="confirm-password"
            name="confirmPassword"
            label={t("auth.confirmPasswordLabel", "Confirm new password")}
            value={confirmPassword}
            onChange={setConfirmPassword}
          />

          <AuthErrorAlert error={error} />

          <AuthSubmitButton
            submitting={submitting}
            label={t("auth.resetPasswordSubmit", "Reset password")}
            loadingLabel={t("auth.resettingPassword", "Resetting…")}
          />

          <AuthBackToLogin label={t("auth.backToLogin", "Back to sign in")} />
        </AuthForm>
      )}

      <AuthFooter />
    </AuthContainer>
  );
}

export const Route = createFileRoute("/reset-password")({
  validateSearch: (search: Record<string, unknown>): ResetPasswordSearch => {
    const token = search["token"];
    return typeof token === "string" ? { token } : {};
  },
  component: ResetPassword,
});
