import type { Meta, StoryObj } from "@storybook/react-vite";

import { ScreenshotDiffViewer } from "./ScreenshotDiffViewer";

import type { components } from "@/lib/api-types";

type ArtifactPublic = components["schemas"]["ArtifactPublic"];

const baseArtifacts: ArtifactPublic[] = [
  {
    id: "art_01",
    run_step_id: "rs_02",
    kind: "SCREENSHOT",
    mime_type: "image/png",
    size_bytes: 102400,
    created_at: "2026-05-27T10:00:30Z",
  },
  {
    id: "art_03",
    run_step_id: "rs_04",
    kind: "SCREENSHOT",
    mime_type: "image/png",
    size_bytes: 98700,
    created_at: "2026-05-27T10:00:45Z",
  },
  {
    id: "art_05",
    run_step_id: "rs_06",
    kind: "SCREENSHOT",
    mime_type: "image/png",
    size_bytes: 110200,
    created_at: "2026-05-27T10:01:00Z",
  },
];

const meta: Meta<typeof ScreenshotDiffViewer> = {
  title: "Runs/ScreenshotDiffViewer",
  component: ScreenshotDiffViewer,
  args: { runId: "run_demo", caseId: "case_demo", artifacts: baseArtifacts },
};

export default meta;

export const Default: StoryObj<typeof ScreenshotDiffViewer> = {};

export const NoScreenshots: StoryObj<typeof ScreenshotDiffViewer> = {
  args: { runId: "run_demo", caseId: "case_demo", artifacts: [] },
};

export const OneScreenshot: StoryObj<typeof ScreenshotDiffViewer> = {
  args: {
    runId: "run_demo",
    caseId: "case_demo",
    artifacts: [baseArtifacts[0] as ArtifactPublic],
  },
};
