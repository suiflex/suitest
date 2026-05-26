import { createFileRoute } from "@tanstack/react-router";

function Login(): React.ReactElement {
  const apiUrl = import.meta.env["VITE_API_URL"] ?? "http://localhost:4000";
  const handleGoogle = (): void => {
    window.location.href = `${apiUrl}/auth/google/authorize`;
  };

  return (
    <section className="mx-auto max-w-md space-y-6 pt-16 text-center">
      <h2 className="text-2xl font-semibold">Sign in to Suitest</h2>
      <p className="text-fg-3">
        Use your Google account to continue. You will be redirected to <code>/dashboard</code> after
        sign-in.
      </p>
      <button
        type="button"
        onClick={handleGoogle}
        className="inline-flex items-center justify-center rounded-md border border-border bg-bg-1 px-4 py-2 font-medium hover:bg-bg-2"
      >
        Continue with Google
      </button>
    </section>
  );
}

export const Route = createFileRoute("/login")({ component: Login });
