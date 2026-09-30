import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ImageLightboxModal } from "./ImageLightboxModal";

describe("<ImageLightboxModal>", () => {
  const sampleSrc = "https://example.com/artifacts/run_1/step_1.png";

  it("does not render dialog content when open is false", () => {
    render(
      <ImageLightboxModal
        open={false}
        onOpenChange={vi.fn()}
        src={sampleSrc}
        title="Step 1: Click button"
      />
    );

    expect(screen.queryByTestId("image-lightbox-modal")).not.toBeInTheDocument();
  });

  it("renders image, title, and action buttons when open is true", () => {
    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        src={sampleSrc}
        alt="Step 1 screenshot"
        title="Step 1: Click button"
        subtitle="image/png"
      />
    );

    expect(screen.getByTestId("image-lightbox-modal")).toBeInTheDocument();
    expect(screen.getByText("Step 1: Click button")).toBeInTheDocument();
    expect(screen.getByText("image/png")).toBeInTheDocument();

    const img = screen.getByTestId("lightbox-image");
    expect(img).toHaveAttribute("src", sampleSrc);
    expect(img).toHaveAttribute("alt", "Step 1 screenshot");

    // Open tab link
    const openTabLink = screen.getByTestId("lightbox-open-tab");
    expect(openTabLink).toHaveAttribute("href", sampleSrc);
    expect(openTabLink).toHaveAttribute("target", "_blank");
    expect(openTabLink).toHaveAttribute("rel", "noreferrer noopener");

    // Download link
    const downloadLink = screen.getByTestId("lightbox-download");
    expect(downloadLink).toHaveAttribute("href", sampleSrc);
    expect(downloadLink).toHaveAttribute(
      "download",
      "step-1-click-button.png"
    );
  });

  it("toggles between Fit mode and 1:1 Actual Size mode on toggle button click", async () => {
    const user = userEvent.setup();
    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        src={sampleSrc}
        title="Step 2"
      />
    );

    const toggleBtn = screen.getByTestId("lightbox-zoom-toggle");
    const viewport = screen.getByTestId("lightbox-viewport");
    const img = screen.getByTestId("lightbox-image");

    // Initial state: Fit mode
    expect(screen.getByText("1:1 Size")).toBeInTheDocument();
    expect(viewport).toHaveClass("cursor-zoom-in");
    expect(img).toHaveClass("object-contain");

    // Click toggle button to enter 1:1 mode
    await user.click(toggleBtn);
    expect(screen.getByText("Fit")).toBeInTheDocument();
    expect(viewport).toHaveClass("cursor-zoom-out");
    expect(img).toHaveClass("max-h-none");

    // Click toggle button again to return to Fit mode
    await user.click(toggleBtn);
    expect(screen.getByText("1:1 Size")).toBeInTheDocument();
    expect(viewport).toHaveClass("cursor-zoom-in");
    expect(img).toHaveClass("object-contain");
  });

  it("toggles zoom mode when clicking on viewport", async () => {
    const user = userEvent.setup();
    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        src={sampleSrc}
        title="Step 3"
      />
    );

    const viewport = screen.getByTestId("lightbox-viewport");
    const img = screen.getByTestId("lightbox-image");

    expect(viewport).toHaveClass("cursor-zoom-in");

    // Click viewport to toggle zoom
    await user.click(viewport);
    expect(viewport).toHaveClass("cursor-zoom-out");
    expect(img).toHaveClass("max-h-none");

    // Click again to toggle back
    await user.click(viewport);
    expect(viewport).toHaveClass("cursor-zoom-in");
    expect(img).toHaveClass("object-contain");
  });

  it("calls onOpenChange(false) when close button is clicked", async () => {
    const user = userEvent.setup();
    const onOpenChange = vi.fn();

    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={onOpenChange}
        src={sampleSrc}
        title="Step 4"
      />
    );

    const closeBtn = screen.getByRole("button", { name: /close/i });
    await user.click(closeBtn);

    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("renders multi-image gallery with counter, navigation buttons, and keyboard shortcuts", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    const galleryImages = [
      { src: "https://example.com/img1.png", title: "Image 1" },
      { src: "https://example.com/img2.png", title: "Image 2" },
      { src: "https://example.com/img3.png", title: "Image 3" },
    ];

    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        images={galleryImages}
        currentIndex={1}
        onNavigate={onNavigate}
      />
    );

    // Counter badge: 2 / 3
    expect(screen.getByTestId("lightbox-image-counter")).toHaveTextContent("2 / 3");
    expect(screen.getByText("Image 2")).toBeInTheDocument();

    // Next button click
    const nextBtn = screen.getByTestId("lightbox-next-btn");
    await user.click(nextBtn);
    expect(onNavigate).toHaveBeenCalledWith(2);

    // Previous button click
    const prevBtn = screen.getByTestId("lightbox-prev-btn");
    await user.click(prevBtn);
    expect(onNavigate).toHaveBeenCalledWith(0);

    // Keyboard ArrowRight
    await user.keyboard("{ArrowRight}");
    expect(onNavigate).toHaveBeenCalledWith(2);

    // Keyboard ArrowLeft
    await user.keyboard("{ArrowLeft}");
    expect(onNavigate).toHaveBeenCalledWith(0);
  });

  it("renders phase buttons and allows switching between before and after in modal", async () => {
    const user = userEvent.setup();
    const onSelectPhase = vi.fn();
    const phases = [
      { id: "shot_before", label: "Before action (highlight)", phase: "before", isSelected: true },
      { id: "shot_after", label: "After action", phase: "after", isSelected: false },
    ];

    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        src="https://example.com/shot_before.png"
        title="Step 3: Click login button"
        phases={phases}
        onSelectPhase={onSelectPhase}
      />
    );

    // Phase navigator is rendered
    expect(screen.getByTestId("lightbox-phase-navigator")).toBeInTheDocument();

    const beforeBtn = screen.getByTestId("lightbox-phase-btn-before");
    const afterBtn = screen.getByTestId("lightbox-phase-btn-after");
    expect(beforeBtn).toBeInTheDocument();
    expect(afterBtn).toBeInTheDocument();

    // Click after button
    await user.click(afterBtn);
    expect(onSelectPhase).toHaveBeenCalledWith("shot_after");

    // Keyboard shortcut 'a' for after
    await user.keyboard("a");
    expect(onSelectPhase).toHaveBeenCalledWith("shot_after");

    // Keyboard shortcut 'b' for before
    await user.keyboard("b");
    expect(onSelectPhase).toHaveBeenCalledWith("shot_before");

    // Keyboard shortcut 'p' to toggle phase
    await user.keyboard("p");
    expect(onSelectPhase).toHaveBeenCalledWith("shot_after");
  });

  it("cycles through more than two phases correctly with 'p' shortcut", async () => {
    const user = userEvent.setup();
    const onSelectPhase = vi.fn();
    const phases = [
      { id: "shot_1", label: "Phase 1", phase: "before", isSelected: false },
      { id: "shot_2", label: "Phase 2", phase: "during", isSelected: true },
      { id: "shot_3", label: "Phase 3", phase: "after", isSelected: false },
    ];

    render(
      <ImageLightboxModal
        open={true}
        onOpenChange={vi.fn()}
        src="https://example.com/shot_2.png"
        title="Step 3: Multi-phase"
        phases={phases}
        onSelectPhase={onSelectPhase}
      />
    );

    await user.keyboard("p");
    expect(onSelectPhase).toHaveBeenCalledWith("shot_3");
  });
});
