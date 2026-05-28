import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  /** Render prop receiving the captured error + a reset handler. */
  fallback: (args: { error: Error; reset: () => void }) => ReactNode;
  children: ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * Minimal class-based ErrorBoundary. We only need this for the read-only
 * screens in M1b — TanStack Router will get its own router-level error
 * surface in a later milestone. Resetting the boundary clears the captured
 * error so the caller's retry handler can re-invoke the failing query.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error: error instanceof Error ? error : new Error(String(error)) };
  }

  override componentDidCatch(error: unknown, info: ErrorInfo): void {
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset = (): void => {
    this.setState({ error: null });
  };

  override render(): ReactNode {
    if (this.state.error) {
      return this.props.fallback({ error: this.state.error, reset: this.reset });
    }
    return this.props.children;
  }
}
