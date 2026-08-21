import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ScreenshotDiffViewer } from "@/components/runs/ScreenshotDiffViewer";
import type { components } from "@/lib/api-types";

type ArtifactPublic = components["schemas"]["ArtifactPublic"];

/** Render inside a QueryClientProvider (the viewer uses useQuery). */
function renderViewer(props: React.ComponentProps<typeof ScreenshotDiffViewer>): void {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <ScreenshotDiffViewer {...props} />
    </QueryClientProvider>,
  );
}

function screenshot(id: string, runStepId = "rs_02"): ArtifactPublic {
  return {
    id,
    run_step_id: runStepId,
    kind: "SCREENSHOT",
    mime_type: "image/png",
    size_bytes: 1024,
    created_at: "2026-05-27T10:00:30Z",
  };
}

describe("<ScreenshotDiffViewer>", () => {
  it("shows an empty state when fewer than 2 screenshots", () => {
    renderViewer({ runId: "run_1", artifacts: [screenshot("a")] });
    expect(screen.getByTestId("screenshot-diff-empty")).toBeInTheDocument();
    expect(
      screen.getByText(/fewer than two screenshots/i),
    ).toBeInTheDocument();
  });

  it("shows an empty state for zero screenshots", () => {
    renderViewer({ runId: "run_1", artifacts: [] });
    expect(screen.getByTestId("screenshot-diff-empty")).toBeInTheDocument();
  });

  it("renders pickers A and B with two screenshots available", () => {
    renderViewer({
      runId: "run_1",
      artifacts: [screenshot("art_01"), screenshot("art_02")],
    });
    expect(screen.getByTestId("diff-pick-a")).toBeInTheDocument();
    expect(screen.getByTestId("diff-pick-b")).toBeInTheDocument();
    // Each picker offers both screenshots.
    const a = screen.getByTestId("diff-pick-a") as HTMLSelectElement;
    expect(a.options.length).toBe(2);
    expect(a.options[0]?.value).toBe("art_01");
    expect(a.options[1]?.value).toBe("art_02");
  });

  it("defaults pickers to the first two screenshots", () => {
    renderViewer({
      runId: "run_1",
      artifacts: [screenshot("art_01"), screenshot("art_02")],
    });
    expect(
      (screen.getByTestId("diff-pick-a") as HTMLSelectElement).value,
    ).toBe("art_01");
    expect(
      (screen.getByTestId("diff-pick-b") as HTMLSelectElement).value,
    ).toBe("art_02");
  });

  it("exposes the pixel mode toggle and the disabled perceptual stub", () => {
    renderViewer({
      runId: "run_1",
      artifacts: [screenshot("a"), screenshot("b")],
    });
    expect(screen.getByTestId("diff-mode-pixel")).toBeInTheDocument();
    const perceptual = screen.getByTestId("diff-mode-perceptual") as HTMLButtonElement;
    expect(perceptual.disabled).toBe(true);
  });

  it("exposes all three view modes", () => {
    renderViewer({
      runId: "run_1",
      artifacts: [screenshot("a"), screenshot("b")],
    });
    expect(screen.getByTestId("diff-view-side-by-side")).toBeInTheDocument();
    expect(screen.getByTestId("diff-view-overlay")).toBeInTheDocument();
    expect(screen.getByTestId("diff-view-diff")).toBeInTheDocument();
  });

  it("canvas wrap renders (canvas path is skipped under jsdom)", () => {
    renderViewer({
      runId: "run_1",
      artifacts: [screenshot("a"), screenshot("b")],
    });
    // The canvas element is present even if drawing is a no-op in jsdom.
    expect(screen.getByTestId("diff-canvas-wrap")).toBeInTheDocument();
  });
});
