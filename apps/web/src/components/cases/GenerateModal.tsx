import { useQueryClient } from "@tanstack/react-query";
import { Check, CircleDot, FileJson, Link2, Loader2, Sparkles } from "lucide-react";
import { useCallback, useMemo, useRef, useState } from "react";

import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import {
  finalizeRecorderSession,
  generateCrawler,
  generateOpenApi,
  startRecorderSession,
  type GeneratorCaseEvent,
  type RecorderSessionStartResponse,
} from "@/lib/generator-client";
import { cn } from "@/lib/utils";

type Suite = components["schemas"]["SuitePublic"];

/** The three deterministic generators (M2-1..M2-3). All run in ZERO. */
export type GeneratorStrategy = "openapi" | "crawler" | "recorder";

interface StrategyMeta {
  id: GeneratorStrategy;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  target: string;
  mcp: string;
  description: string;
}

const STRATEGIES: StrategyMeta[] = [
  {
    id: "openapi",
    label: "Generate from OpenAPI",
    icon: FileJson,
    target: "BE_REST",
    mcp: "api-mcp",
    description: "Parse an OpenAPI 3.0 spec into a per-operation contract suite.",
  },
  {
    id: "crawler",
    label: "Crawl URL",
    icon: Link2,
    target: "FE_WEB",
    mcp: "playwright-mcp",
    description: "BFS a site from a start URL — smoke + form-fill cases per page.",
  },
  {
    id: "recorder",
    label: "Record from browser",
    icon: CircleDot,
    target: "FE_WEB",
    mcp: "playwright-mcp",
    description: "Drive a live browser; captured actions become a test case.",
  },
];

type Step = "select" | "configure" | "run";
type RunStatus = "idle" | "running" | "done" | "error";

interface GenerateModalProps {
  open: boolean;
  onClose: () => void;
  suites: Suite[];
  projectId: string | null;
  /** Deep-link entry from the split-button dropdown; jumps straight to config. */
  initialStrategy?: GeneratorStrategy;
}

/** McpProvider pill — auto-resolved from the chosen strategy (read-only here). */
function McpPill({ name }: { name: string }): React.ReactElement {
  return (
    <span
      data-testid="gen-mcp-pill"
      className="inline-flex items-center gap-1.5 rounded-md border border-border bg-bg-elev-1 px-2 py-0.5 font-mono text-[11px] text-fg-3"
    >
      <span className="h-1.5 w-1.5 rounded-full bg-accent" aria-hidden="true" />
      {name}
    </span>
  );
}

export function GenerateModal({
  open,
  onClose,
  suites,
  projectId,
  initialStrategy,
}: GenerateModalProps): React.ReactElement {
  const queryClient = useQueryClient();
  const abortRef = useRef<AbortController | null>(null);

  const [step, setStep] = useState<Step>(initialStrategy ? "configure" : "select");
  const [strategy, setStrategy] = useState<GeneratorStrategy | null>(initialStrategy ?? null);

  // Shared config
  const [suiteId, setSuiteId] = useState<string>(suites[0]?.id ?? "");

  // OpenAPI config
  const [specMode, setSpecMode] = useState<"url" | "paste">("url");
  const [specUrl, setSpecUrl] = useState("");
  const [specContent, setSpecContent] = useState("");

  // Crawler config
  const [startUrl, setStartUrl] = useState("");
  const [maxDepth, setMaxDepth] = useState(2);
  const [maxPages, setMaxPages] = useState(20);

  // Recorder config
  const [caseName, setCaseName] = useState("");

  // Run state
  const [status, setStatus] = useState<RunStatus>("idle");
  const [phase, setPhase] = useState<string | null>(null);
  const [cases, setCases] = useState<GeneratorCaseEvent[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [completeCount, setCompleteCount] = useState<number | null>(null);
  const [recorderSession, setRecorderSession] = useState<RecorderSessionStartResponse | null>(null);

  const meta = useMemo(() => STRATEGIES.find((s) => s.id === strategy) ?? null, [strategy]);

  const resetRun = useCallback(() => {
    setStatus("idle");
    setPhase(null);
    setCases([]);
    setErrorMsg(null);
    setCompleteCount(null);
    setRecorderSession(null);
  }, []);

  const handleClose = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    onClose();
  }, [onClose]);

  const invalidateCases = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["test-cases"] });
  }, [queryClient]);

  // --- Validation --------------------------------------------------------
  const configValid = useMemo(() => {
    if (!suiteId) return false;
    switch (strategy) {
      case "openapi":
        return specMode === "url" ? specUrl.trim().length > 0 : specContent.trim().length > 0;
      case "crawler":
        return startUrl.trim().length > 0;
      case "recorder":
        return startUrl.trim().length > 0 && projectId !== null;
      default:
        return false;
    }
  }, [strategy, suiteId, specMode, specUrl, specContent, startUrl, projectId]);

  // --- Streaming generators (openapi / crawler) --------------------------
  const runStreaming = useCallback(async () => {
    resetRun();
    setStatus("running");
    const controller = new AbortController();
    abortRef.current = controller;

    const handlers = {
      onProgress: (e: { phase: string }) => setPhase(e.phase),
      onCase: (e: GeneratorCaseEvent) => setCases((prev) => [...prev, e]),
      onComplete: (e: { cases_created: number }) => {
        setStatus("done");
        setCompleteCount(e.cases_created);
        invalidateCases();
      },
      onError: (e: { message: string }) => {
        setStatus("error");
        setErrorMsg(e.message);
      },
    };

    try {
      if (strategy === "openapi") {
        await generateOpenApi(
          {
            target_suite_id: suiteId,
            ...(specMode === "url" ? { spec_url: specUrl } : { spec_content: specContent }),
          },
          handlers,
          controller.signal,
        );
      } else if (strategy === "crawler") {
        await generateCrawler(
          {
            target_suite_id: suiteId,
            start_url: startUrl,
            options: {
              max_depth: maxDepth,
              max_pages: maxPages,
              same_origin_only: true,
              faker_locale: "en_US",
              include_form_cases: true,
            },
          },
          handlers,
          controller.signal,
        );
      }
    } catch (err) {
      if (controller.signal.aborted) return;
      setStatus("error");
      setErrorMsg(err instanceof Error ? err.message : "Generation failed");
    }
  }, [
    resetRun,
    strategy,
    suiteId,
    specMode,
    specUrl,
    specContent,
    startUrl,
    maxDepth,
    maxPages,
    invalidateCases,
  ]);

  // --- Recorder: start session ------------------------------------------
  const runRecorderStart = useCallback(async () => {
    if (projectId === null) return;
    resetRun();
    setStatus("running");
    try {
      const session = await startRecorderSession({
        project_id: projectId,
        start_url: startUrl,
        mcp_provider: "playwright-mcp",
      });
      setRecorderSession(session);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Could not start recorder");
    }
  }, [projectId, resetRun, startUrl]);

  const runRecorderFinalize = useCallback(async () => {
    if (recorderSession === null) return;
    setStatus("running");
    try {
      await finalizeRecorderSession(recorderSession.session_id, {
        target_suite_id: suiteId,
        name: caseName,
        priority: "P2",
      });
      setStatus("done");
      setCompleteCount(1);
      invalidateCases();
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Could not finalize recording");
    }
  }, [recorderSession, suiteId, caseName, invalidateCases]);

  const goRun = useCallback(() => {
    setStep("run");
    if (strategy === "openapi" || strategy === "crawler") {
      void runStreaming();
    } else if (strategy === "recorder") {
      void runRecorderStart();
    }
  }, [strategy, runStreaming, runRecorderStart]);

  // --- Render helpers ----------------------------------------------------
  const stepIndex = step === "select" ? 1 : step === "configure" ? 2 : 3;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) handleClose();
      }}
    >
      <DialogContent
        data-testid="generate-modal"
        className="border border-border bg-bg-elev-1 sm:max-w-230"
      >
        <DialogHeader>
          <div className="flex items-center justify-between gap-3 pr-6">
            <DialogTitle className="text-fg-1">Generate test cases</DialogTitle>
            <span className="font-mono text-[11px] text-fg-4" data-testid="gen-step-indicator">
              Step {stepIndex} / 3
            </span>
          </div>
          <DialogDescription className="text-fg-3">
            Deterministic generators — no LLM required. Generated cases are saved as DRAFTs in the
            chosen suite.
          </DialogDescription>
        </DialogHeader>

        {/* Step 1: pick a strategy */}
        {step === "select" ? (
          <div className="flex flex-col gap-3" data-testid="gen-select-step">
            <div className="grid grid-cols-3 gap-2">
              {STRATEGIES.map((s) => {
                const Icon = s.icon;
                const active = strategy === s.id;
                return (
                  <button
                    key={s.id}
                    type="button"
                    data-testid={`gen-strategy-${s.id}`}
                    data-active={active ? "true" : "false"}
                    onClick={() => {
                      setStrategy(s.id);
                    }}
                    className={cn(
                      "flex flex-col gap-1.5 rounded-md border border-border bg-bg-elev-2 p-3 text-left hover:border-fg-4",
                      active && "border-accent bg-accent/10",
                    )}
                  >
                    <Icon className="h-4 w-4 text-fg-1" aria-hidden="true" />
                    <span className="text-[12.5px] font-medium text-fg-1">{s.label}</span>
                    <span className="text-[11px] leading-snug text-fg-4">{s.description}</span>
                    <McpPill name={s.mcp} />
                  </button>
                );
              })}
            </div>
            {/* AI strategies — grayed in ZERO */}
            <div className="grid grid-cols-2 gap-2">
              <DisabledTooltip reason="Requires LLM. Settings → LLM">
                <div
                  data-testid="gen-strategy-ai-enrich"
                  className="flex cursor-not-allowed items-center gap-2 rounded-md border border-border bg-bg-elev-2 p-3 opacity-50"
                >
                  <Sparkles className="h-4 w-4 text-violet" aria-hidden="true" />
                  <span className="text-[12px] text-fg-3">AI-enrich (edge cases, negatives)</span>
                </div>
              </DisabledTooltip>
              <DisabledTooltip reason="Requires LLM. Settings → LLM">
                <div
                  data-testid="gen-strategy-ai-only"
                  className="flex cursor-not-allowed items-center gap-2 rounded-md border border-border bg-bg-elev-2 p-3 opacity-50"
                >
                  <Sparkles className="h-4 w-4 text-violet" aria-hidden="true" />
                  <span className="text-[12px] text-fg-3">AI-only (PRD, semantic)</span>
                </div>
              </DisabledTooltip>
            </div>
          </div>
        ) : null}

        {/* Step 2: configure source */}
        {step === "configure" && meta ? (
          <div className="flex flex-col gap-3" data-testid="gen-configure-step">
            <div className="flex items-center gap-2 text-[12px] text-fg-3">
              <meta.icon className="h-4 w-4 text-fg-1" aria-hidden="true" />
              <span className="font-medium text-fg-1">{meta.label}</span>
              <span className="text-fg-5">·</span>
              <McpPill name={meta.mcp} />
            </div>

            <div className="flex flex-col gap-1.5">
              <Label htmlFor="gen-suite" className="text-[11px] text-fg-4">
                Target suite
              </Label>
              <select
                id="gen-suite"
                data-testid="gen-suite-select"
                value={suiteId}
                onChange={(e) => {
                  setSuiteId(e.target.value);
                }}
                className="h-9 rounded-md border border-border bg-bg-elev-1 px-2 text-[12.5px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
              >
                {suites.length === 0 ? (
                  <option value="">No suites — create one first</option>
                ) : null}
                {suites.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </div>

            {strategy === "openapi" ? (
              <div className="flex flex-col gap-2">
                <div className="flex items-center gap-2 text-[11px]">
                  <button
                    type="button"
                    data-testid="gen-openapi-mode-url"
                    data-active={specMode === "url" ? "true" : "false"}
                    onClick={() => {
                      setSpecMode("url");
                    }}
                    className={cn(
                      "rounded-md px-2 py-1 text-fg-3 hover:bg-bg-elev-2",
                      specMode === "url" && "bg-bg-elev-2 text-fg-1",
                    )}
                  >
                    Spec URL
                  </button>
                  <button
                    type="button"
                    data-testid="gen-openapi-mode-paste"
                    data-active={specMode === "paste" ? "true" : "false"}
                    onClick={() => {
                      setSpecMode("paste");
                    }}
                    className={cn(
                      "rounded-md px-2 py-1 text-fg-3 hover:bg-bg-elev-2",
                      specMode === "paste" && "bg-bg-elev-2 text-fg-1",
                    )}
                  >
                    Paste spec
                  </button>
                </div>
                {specMode === "url" ? (
                  <Input
                    data-testid="gen-openapi-url"
                    placeholder="https://api.example.com/openapi.json"
                    value={specUrl}
                    onChange={(e) => {
                      setSpecUrl(e.target.value);
                    }}
                  />
                ) : (
                  <textarea
                    data-testid="gen-openapi-spec"
                    placeholder="Paste OpenAPI 3.0 JSON or YAML…"
                    value={specContent}
                    onChange={(e) => {
                      setSpecContent(e.target.value);
                    }}
                    rows={6}
                    className="rounded-md border border-border bg-bg-elev-1 p-2 font-mono text-[11.5px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
                  />
                )}
              </div>
            ) : null}

            {strategy === "crawler" ? (
              <div className="flex flex-col gap-2">
                <Input
                  data-testid="gen-crawler-url"
                  placeholder="https://app.example.com"
                  value={startUrl}
                  onChange={(e) => {
                    setStartUrl(e.target.value);
                  }}
                />
                <div className="grid grid-cols-2 gap-2">
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="gen-depth" className="text-[11px] text-fg-4">
                      Max depth (1–5)
                    </Label>
                    <Input
                      id="gen-depth"
                      data-testid="gen-crawler-depth"
                      type="number"
                      min={1}
                      max={5}
                      value={maxDepth}
                      onChange={(e) => {
                        setMaxDepth(Number(e.target.value));
                      }}
                    />
                  </div>
                  <div className="flex flex-col gap-1">
                    <Label htmlFor="gen-pages" className="text-[11px] text-fg-4">
                      Max pages (1–200)
                    </Label>
                    <Input
                      id="gen-pages"
                      data-testid="gen-crawler-pages"
                      type="number"
                      min={1}
                      max={200}
                      value={maxPages}
                      onChange={(e) => {
                        setMaxPages(Number(e.target.value));
                      }}
                    />
                  </div>
                </div>
              </div>
            ) : null}

            {strategy === "recorder" ? (
              <div className="flex flex-col gap-2">
                <Input
                  data-testid="gen-recorder-url"
                  placeholder="https://app.example.com/login"
                  value={startUrl}
                  onChange={(e) => {
                    setStartUrl(e.target.value);
                  }}
                />
                <div className="flex flex-col gap-1">
                  <Label htmlFor="gen-name" className="text-[11px] text-fg-4">
                    Case name
                  </Label>
                  <Input
                    id="gen-name"
                    data-testid="gen-recorder-name"
                    placeholder="Login happy path"
                    value={caseName}
                    onChange={(e) => {
                      setCaseName(e.target.value);
                    }}
                  />
                </div>
                {projectId === null ? (
                  <p className="text-[11px] text-amber">
                    Select an active project before recording.
                  </p>
                ) : null}
              </div>
            ) : null}
          </div>
        ) : null}

        {/* Step 3: run / review */}
        {step === "run" && meta ? (
          <div className="flex flex-col gap-3" data-testid="gen-run-step">
            {strategy === "recorder" ? (
              <RecorderRunPanel
                session={recorderSession}
                status={status}
                caseName={caseName}
                completed={completeCount !== null}
                onStart={() => void runRecorderStart()}
                onFinalize={() => void runRecorderFinalize()}
              />
            ) : (
              <>
                {status === "running" ? (
                  <div
                    data-testid="gen-progress"
                    className="flex items-center gap-2 text-[12px] text-fg-3"
                  >
                    <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" aria-hidden="true" />
                    {phase ? `Generating (${phase})…` : "Generating…"}
                  </div>
                ) : null}

                <ul
                  className="flex max-h-70 flex-col gap-1 overflow-y-auto"
                  data-testid="gen-case-list"
                >
                  {cases.map((c) => (
                    <li
                      key={c.public_id}
                      data-testid="gen-case-row"
                      className="flex items-center gap-2 rounded-md border border-border bg-bg-elev-2 px-2 py-1.5 text-[12px]"
                    >
                      <span className="shrink-0 font-mono text-[11px] text-fg-4">
                        {c.public_id}
                      </span>
                      <span className="min-w-0 flex-1 truncate text-fg-1">{c.name}</span>
                      {c.case_kind ? (
                        <span className="shrink-0 rounded border border-border px-1 font-mono text-[10px] text-fg-4">
                          {c.case_kind}
                        </span>
                      ) : null}
                    </li>
                  ))}
                </ul>

                {status === "done" ? (
                  <div
                    data-testid="gen-complete"
                    className="flex items-center gap-2 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-[12px] text-fg-1"
                  >
                    <Check className="h-4 w-4 text-accent" aria-hidden="true" />
                    {completeCount ?? cases.length} case
                    {(completeCount ?? cases.length) === 1 ? "" : "s"} added to the suite.
                  </div>
                ) : null}

                {status === "error" ? (
                  <div
                    data-testid="gen-error"
                    className="rounded-md border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red"
                  >
                    {errorMsg ?? "Generation failed."}
                  </div>
                ) : null}
              </>
            )}
          </div>
        ) : null}

        {/* Footer */}
        <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
          <div>
            {step !== "select" && status !== "running" ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                data-testid="gen-back"
                onClick={() => {
                  if (step === "run") {
                    resetRun();
                    setStep("configure");
                  } else {
                    setStep("select");
                  }
                }}
              >
                Back
              </Button>
            ) : null}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              data-testid="gen-cancel"
              onClick={handleClose}
            >
              {status === "done" ? "Close" : "Cancel"}
            </Button>
            {step === "select" ? (
              <Button
                type="button"
                size="sm"
                data-testid="gen-next"
                disabled={strategy === null}
                onClick={() => {
                  setStep("configure");
                }}
              >
                Next
              </Button>
            ) : null}
            {step === "configure" ? (
              <Button
                type="button"
                size="sm"
                data-testid="gen-run-btn"
                disabled={!configValid}
                onClick={goRun}
              >
                {strategy === "recorder" ? "Start recording" : "Generate"}
              </Button>
            ) : null}
            {step === "run" && status === "done" ? (
              <Button type="button" size="sm" data-testid="gen-done" onClick={handleClose}>
                Done
              </Button>
            ) : null}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

// ---------------------------------------------------------------------------
// Recorder sub-panel — start → live session → finalize.
// ---------------------------------------------------------------------------

function RecorderRunPanel({
  session,
  status,
  caseName,
  completed,
  onStart,
  onFinalize,
}: {
  session: RecorderSessionStartResponse | null;
  status: RunStatus;
  caseName: string;
  completed: boolean;
  onStart: () => void;
  onFinalize: () => void;
}): React.ReactElement {
  if (completed) {
    return (
      <div
        data-testid="gen-complete"
        className="flex items-center gap-2 rounded-md border border-accent/40 bg-accent/10 px-3 py-2 text-[12px] text-fg-1"
      >
        <Check className="h-4 w-4 text-accent" aria-hidden="true" />
        Recording saved as a DRAFT case in the suite.
      </div>
    );
  }

  if (session === null) {
    return (
      <div className="flex flex-col gap-2" data-testid="gen-recorder-start-panel">
        <p className="text-[12px] text-fg-3">
          Opens a live browser session. Interact with the page, then finalize to convert the
          captured actions into a test case.
        </p>
        <Button
          type="button"
          size="sm"
          data-testid="gen-recorder-start"
          disabled={status === "running"}
          onClick={onStart}
          className="self-start"
        >
          {status === "running" ? "Opening…" : "Open recording session"}
        </Button>
        {status === "error" ? (
          <div data-testid="gen-error" className="text-[12px] text-red">
            Could not start the recorder.
          </div>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2" data-testid="gen-recorder-live-panel">
      <div className="flex items-center gap-2 text-[12px] text-fg-3">
        <CircleDot className="h-3.5 w-3.5 animate-pulse text-red" aria-hidden="true" />
        Recording — session{" "}
        <span className="font-mono text-[11px] text-fg-4">{session.session_id}</span>
      </div>
      {session.browser_url ? (
        <a
          href={session.browser_url}
          target="_blank"
          rel="noreferrer"
          data-testid="gen-recorder-browser-link"
          className="text-[12px] text-accent underline"
        >
          Open live browser ↗
        </a>
      ) : null}
      <Button
        type="button"
        size="sm"
        data-testid="gen-recorder-finalize"
        disabled={status === "running" || caseName.trim().length === 0}
        onClick={onFinalize}
        className="self-start"
      >
        {status === "running" ? "Finalizing…" : "Finalize → create case"}
      </Button>
    </div>
  );
}
