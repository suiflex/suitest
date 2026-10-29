import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  createMemoryHistory,
  createRootRoute,
  createRouter,
  RouterProvider,
} from "@tanstack/react-router";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  AuthBackToLogin,
  AuthContainer,
  AuthErrorAlert,
  AuthFooter,
  AuthHeader,
  AuthPasswordInput,
  AuthSubmitButton,
  AuthSuccessCard,
} from "@/components/shared/AuthLayout";

describe("AuthLayout components", () => {
  it("renders AuthHeader with logo, title, and subtitle", () => {
    render(<AuthHeader subtitle="Please enter your email" />);
    expect(screen.getByAltText("Suitest")).toBeInTheDocument();
    expect(screen.getByText("Please enter your email")).toBeInTheDocument();
  });

  it("renders AuthSubmitButton in idle and submitting states", () => {
    const { rerender } = render(
      <AuthSubmitButton submitting={false} label="Send link" loadingLabel="Sending…" />,
    );
    const button = screen.getByRole("button", { name: "Send link" });
    expect(button).toBeEnabled();

    rerender(
      <AuthSubmitButton submitting={true} label="Send link" loadingLabel="Sending…" />,
    );
    expect(screen.getByRole("button", { name: "Sending…" })).toBeDisabled();
  });

  it("renders AuthPasswordInput with label and triggers onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <AuthPasswordInput
        id="test-pass"
        name="testPass"
        label="Password Label"
        value=""
        onChange={onChange}
      />,
    );
    expect(screen.getByLabelText("Password Label")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Password Label"), "a");
    expect(onChange).toHaveBeenCalledWith("a");
  });

  it("renders AuthErrorAlert when error exists, null otherwise", () => {
    const { rerender } = render(<AuthErrorAlert error="Sample error" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Sample error");

    rerender(<AuthErrorAlert error={null} />);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("renders AuthFooter with copyright text", () => {
    render(<AuthFooter />);
    expect(screen.getByText(/© 2026 Suitest contributors/i)).toBeInTheDocument();
  });

  it("renders AuthContainer wrapping children", () => {
    render(
      <AuthContainer>
        <div data-testid="child-content">Child</div>
      </AuthContainer>,
    );
    expect(screen.getByTestId("child-content")).toBeInTheDocument();
  });

  it("renders AuthBackToLogin with Link", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const rootRoute = createRootRoute({
      component: () => <AuthBackToLogin label="Back to sign in" />,
    });
    const router = createRouter({
      routeTree: rootRoute,
      history: createMemoryHistory({ initialEntries: ["/"] }),
      context: { queryClient },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByRole("link", { name: "Back to sign in" })).toHaveAttribute(
      "href",
      "/login",
    );
  });

  it("renders AuthSuccessCard with title, description, and action link", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const rootRoute = createRootRoute({
      component: () => (
        <AuthSuccessCard
          title="Success Title"
          description="Success Description"
          titleTestId="test-title"
          descTestId="test-desc"
          actionLabel="Go to Login"
        />
      ),
    });
    const router = createRouter({
      routeTree: rootRoute,
      history: createMemoryHistory({ initialEntries: ["/"] }),
      context: { queryClient },
    });
    render(
      <QueryClientProvider client={queryClient}>
        <RouterProvider router={router} />
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("test-title")).toHaveTextContent("Success Title");
    expect(screen.getByTestId("test-desc")).toHaveTextContent("Success Description");
    expect(screen.getByRole("link", { name: "Go to Login" })).toHaveAttribute("href", "/login");
  });
});
