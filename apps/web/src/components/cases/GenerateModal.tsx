import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  CheckCircle2,
  CircleDot,
  Compass,
  FileJson,
  Keyboard,
  Link2,
  ListFilter,
  Loader2,
  MousePointerClick,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Sparkles,
  Trash2,
  Upload,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

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
import type { McpProvidersPage } from "@/hooks/use-integrations";
import { api, ApiError } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import {
  cancelRecorderSession,
  finalizeRecorderSession,
  generateCrawler,
  generateOpenApi,
  getRecorderSession,
  resumeRecorderSession,
  startRecorderSession,
  syncRecorderSession,
  type GeneratorCaseEvent,
  type RecorderCapturedEvent,
  type RecorderSessionStartResponse,
} from "@/lib/generator-client";
import { cn } from "@/lib/utils";

type Suite = components["schemas"]["SuitePublic"];

const EMAIL_PATTERN = /@/;
function toDynamicVariableTemplate(text: string): string {
  if (EMAIL_PATTERN.test(text)) {
    return "{{email}}";
  }
  const clean = text.toLowerCase().replace(/[^a-z0-9]/g, "_").slice(0, 16);
  return `{{${clean || "var"}}}`;
}

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
  const [mcpProvider, setMcpProvider] = useState("playwright-mcp");

  // Run state
  const [status, setStatus] = useState<RunStatus>("idle");
  const [phase, setPhase] = useState<string | null>(null);
  const [cases, setCases] = useState<GeneratorCaseEvent[]>([]);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [completeCount, setCompleteCount] = useState<number | null>(null);
  const [recorderSession, setRecorderSession] = useState<RecorderSessionStartResponse | null>(null);

  const { data: providersData } = useQuery<McpProvidersPage>({
    queryKey: ["mcp", "providers"],
    queryFn: async () => (await api.get<McpProvidersPage>("/mcp/providers")).data,
    enabled: open,
  });

  const browserProviders = useMemo(() => {
    if (!providersData?.items) return [];
    const browserRe = /playwright|browser/i;
    return providersData.items.filter(
      (p) => p.kind === "FE_WEB" || browserRe.test(p.id) || browserRe.test(p.name),
    );
  }, [providersData]);

  const meta = useMemo(() => STRATEGIES.find((s) => s.id === strategy) ?? null, [strategy]);

  const activeSessionIdRef = useRef<string | null>(null);
  activeSessionIdRef.current = recorderSession?.session_id ?? null;

  const statusRef = useRef<RunStatus>(status);
  statusRef.current = status;

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
    if (activeSessionIdRef.current && statusRef.current !== "done") {
      const sid = activeSessionIdRef.current;
      activeSessionIdRef.current = null;
      void cancelRecorderSession(sid).catch((err) => {
        console.debug("Failed to cancel recorder session:", err);
      });
    }
    onClose();
  }, [onClose]);

  useEffect(() => {
    return () => {
      if (activeSessionIdRef.current && statusRef.current !== "done") {
        const sid = activeSessionIdRef.current;
        activeSessionIdRef.current = null;
        void cancelRecorderSession(sid).catch(() => {});
      }
    };
  }, []);

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
        mcp_provider: mcpProvider || "playwright-mcp",
      });
      setRecorderSession(session);
      setStatus("idle");
    } catch (err) {
      setStatus("error");
      setErrorMsg(err instanceof ApiError ? err.message : "Could not start recorder");
    }
  }, [projectId, resetRun, startUrl, mcpProvider]);

  const runRecorderFinalize = useCallback(
    async (customEvents?: RecorderCapturedEvent[]) => {
      if (recorderSession === null) return;
      setStatus("running");
      try {
        await finalizeRecorderSession(recorderSession.session_id, {
          target_suite_id: suiteId,
          name: caseName,
          priority: "P2",
          ...(customEvents && customEvents.length > 0
            ? { events: customEvents as unknown as Record<string, unknown>[] }
            : {}),
        });
        setStatus("done");
        setCompleteCount(1);
        invalidateCases();
      } catch (err) {
        setStatus("error");
        setErrorMsg(err instanceof ApiError ? err.message : "Could not finalize recording");
      }
    },
    [recorderSession, suiteId, caseName, invalidateCases],
  );

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
        className="border border-border bg-bg-elev-1 sm:max-w-230 max-h-[90vh] flex flex-col overflow-hidden"
      >
        <DialogHeader className="shrink-0">
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
          <div className="flex flex-col gap-3 flex-1 overflow-y-auto min-h-0 pr-1" data-testid="gen-select-step">
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
          <div className="flex flex-col gap-3 flex-1 overflow-y-auto min-h-0 pr-1" data-testid="gen-configure-step">
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
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1">
                  <Label htmlFor="gen-recorder-url" className="text-[11px] text-fg-4">
                    Target application URL
                  </Label>
                  <Input
                    id="gen-recorder-url"
                    data-testid="gen-recorder-url"
                    placeholder="https://app.example.com/login"
                    value={startUrl}
                    onChange={(e) => {
                      setStartUrl(e.target.value);
                    }}
                  />
                  <span className="text-[10.5px] text-fg-4">
                    Initial web address opened in the browser when recording starts.
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="gen-name" className="text-[11px] text-fg-4">
                    Test case name
                  </Label>
                  <Input
                    id="gen-name"
                    data-testid="gen-recorder-name"
                    placeholder="e.g. Login with valid credentials"
                    value={caseName}
                    onChange={(e) => {
                      setCaseName(e.target.value);
                    }}
                  />
                  <span className="text-[10.5px] text-fg-4">
                    Name for the test case saved in your test suite upon finalization.
                  </span>
                </div>
                <div className="flex flex-col gap-1">
                  <Label htmlFor="gen-recorder-mcp" className="text-[11px] text-fg-4">
                    Browser recording mode / provider
                  </Label>
                  <select
                    id="gen-recorder-mcp"
                    data-testid="gen-recorder-mcp-select"
                    value={mcpProvider}
                    onChange={(e) => {
                      setMcpProvider(e.target.value);
                    }}
                    className="h-9 rounded-md border border-border bg-bg-elev-1 px-2.5 text-[12.5px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
                  >
                    {browserProviders.length === 0 ? (
                      <option value="playwright-mcp">Native Headed Chrome (Desktop Window)</option>
                    ) : (
                      <>
                        <option value="playwright-mcp">Native Headed Chrome (Desktop Window)</option>
                        {browserProviders.map((p) => (
                          <option key={p.id} value={p.id}>
                            {p.name} ({p.id})
                          </option>
                        ))}
                      </>
                    )}
                  </select>
                  <span className="text-[10.5px] text-fg-4">
                    Native Chrome opens directly on your desktop with zero proxy lag and full CDP event capture.
                  </span>
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
          <div className="flex flex-col gap-3 flex-1 overflow-y-auto min-h-0 pr-1" data-testid="gen-run-step">
            {strategy === "recorder" ? (
              <RecorderRunPanel
                session={recorderSession}
                status={status}
                caseName={caseName}
                startUrl={startUrl}
                completed={completeCount !== null}
                errorMsg={errorMsg}
                mcpProvider={mcpProvider}
                onStart={() => void runRecorderStart()}
                onFinalize={(customEvents) => void runRecorderFinalize(customEvents)}
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
        <div className="flex items-center justify-between gap-2 border-t border-border pt-3 shrink-0 mt-auto">
          <div>
            {step !== "select" && status !== "running" ? (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                data-testid="gen-back"
                onClick={() => {
                  if (step === "run") {
                    if (activeSessionIdRef.current && statusRef.current !== "done") {
                      const sid = activeSessionIdRef.current;
                      activeSessionIdRef.current = null;
                      void cancelRecorderSession(sid).catch(() => {});
                    }
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

// Helper to coalesce consecutive redundant actions (e.g. duplicate navigations, rapid clicks, typing or click+type on same selector)
function coalesceEvents(eventList: RecorderCapturedEvent[]): RecorderCapturedEvent[] {
  const coalesced: RecorderCapturedEvent[] = [];
  for (const evt of eventList) {
    if (evt.kind === "type" && (!evt.text || evt.text.trim() === "")) {
      continue;
    }
    // Filter accidental background clicks on root body or html
    if (evt.kind === "click" && (evt.selector === "body" || evt.selector === "html")) {
      continue;
    }
    if (!coalesced.length) {
      coalesced.push(evt);
      continue;
    }
    const prev = coalesced[coalesced.length - 1];
    // Deduplicate consecutive navigations to identical URL
    if (prev && prev.kind === "navigate" && evt.kind === "navigate" && prev.url === evt.url) {
      continue;
    }
    // Drop redundant navigate event that immediately follows a click on link/button or select
    if (prev && (prev.kind === "click" || prev.kind === "select") && evt.kind === "navigate") {
      continue;
    }
    // Deduplicate consecutive duplicate clicks on same selector only within micro-debounce (< 200ms)
    // to filter hardware double-click bounce without dropping intentional rapid clicks
    if (
      prev &&
      prev.kind === "click" &&
      evt.kind === "click" &&
      prev.selector === evt.selector
    ) {
      if (prev.timestamp && evt.timestamp) {
        const diff = Math.abs(new Date(evt.timestamp).getTime() - new Date(prev.timestamp).getTime());
        if (diff < 200) continue;
      }
    }
    if (prev && prev.kind === "type" && evt.kind === "type" && prev.selector === evt.selector) {
      coalesced[coalesced.length - 1] = evt;
      continue;
    }
    if (prev && prev.kind === "click" && evt.kind === "type" && prev.selector === evt.selector) {
      coalesced[coalesced.length - 1] = evt;
      continue;
    }
    coalesced.push(evt);
  }
  return coalesced;
}

// ---------------------------------------------------------------------------
// Recorder sub-panel — start → live session → finalize.
// ---------------------------------------------------------------------------

function RecorderRunPanel({
  session,
  status,
  caseName,
  startUrl,
  completed,
  errorMsg,
  onStart,
  onFinalize,
}: {
  session: RecorderSessionStartResponse | null;
  status: RunStatus;
  caseName: string;
  startUrl: string;
  completed: boolean;
  errorMsg?: string | null;
  mcpProvider?: string;
  onStart: () => void;
  onFinalize: (customEvents: RecorderCapturedEvent[]) => void;
}): React.ReactElement {
  const [events, setEvents] = useState<RecorderCapturedEvent[]>([]);
  const [userHasEdited, setUserHasEdited] = useState(false);
  const [editingIdx, setEditingIdx] = useState<number | null>(null);
  const [editDraft, setEditDraft] = useState<RecorderCapturedEvent | null>(null);
  const [browserClosed, setBrowserClosed] = useState(false);
  const [hudFinished, setHudFinished] = useState(false);
  const [resuming, setResuming] = useState(false);

  // Track the number of events received from the server to allow incremental merging
  // even after the user edits, deletes, or reorders recorded steps.
  const lastServerCountRef = useRef(0);
  const userHasEditedRef = useRef(userHasEdited);
  userHasEditedRef.current = userHasEdited;

  useEffect(() => {
    // Keep polling active even when userHasEdited is true so new actions captured
    // by the browser continue to stream into the steps list without interruption.
    if (!session || completed || status === "error") return;

    let cancelled = false;
    const fetchEvents = async () => {
      try {
        const detail = await getRecorderSession(session.session_id);
        if (cancelled) return;

        // If session was finalized directly from backend
        if (detail.status === "finalized" && !completed) {
          onFinalize(detail.captured_events ?? []);
          return;
        }

        // Detect headed browser window closure or HUD finalization
        if (detail.status === "active") {
          if (detail.hud_finished) {
            setBrowserClosed(true);
            setHudFinished(true);
          } else if (detail.is_headed_active === false) {
            setBrowserClosed(true);
          } else if (detail.is_headed_active === true) {
            setBrowserClosed(false);
            setHudFinished(false);
          }
        }

        if (detail.captured_events) {
          const rawEvents = detail.captured_events ?? [];
          const currentServerCount = rawEvents.length;

          if (detail.hud_finished) {
            // When HUD has finalized, server's captured_events are the finalized, edited steps from the HUD!
            // We sync them directly without re-inserting navigations or running destructive coalescing.
            lastServerCountRef.current = currentServerCount;
            setEvents(rawEvents);
          } else if (!userHasEditedRef.current) {
            // Full sync from server
            const firstEvent = rawEvents[0];
            const hasNav = Boolean(
              firstEvent &&
                firstEvent.kind === "navigate" &&
                firstEvent.url &&
                !firstEvent.url.startsWith("about:"),
            );
            const targetUrl = startUrl.startsWith("http") ? startUrl : `https://${startUrl}`;
            const initialEvents =
              !hasNav && startUrl
                ? [
                    {
                      kind: "navigate" as const,
                      url: targetUrl,
                      timestamp: new Date().toISOString(),
                    },
                    ...rawEvents,
                  ]
                : rawEvents;

            lastServerCountRef.current = currentServerCount;
            setEvents(coalesceEvents(initialEvents));
          } else {
            // User has modified steps. If new actions have arrived from the browser,
            // incrementally append and coalesce only the newly recorded events.
            if (currentServerCount > lastServerCountRef.current) {
              const newRaw = rawEvents.slice(lastServerCountRef.current);
              lastServerCountRef.current = currentServerCount;
              setEvents((prev) => coalesceEvents([...prev, ...newRaw]));
            }
          }
        }
      } catch {
        // Silently tolerate polling errors during recording
      }
    };

    void fetchEvents();
    const interval = setInterval(fetchEvents, 500);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [session, completed, status, startUrl, onFinalize]);

  const handleResumeBrowser = async () => {
    if (!session || resuming) return;
    setResuming(true);
    try {
      await resumeRecorderSession(session.session_id);
      setBrowserClosed(false);
      setHudFinished(false);
    } catch (err) {
      console.error("Failed to resume browser session:", err);
    } finally {
      setResuming(false);
    }
  };

  const markUserEdited = () => {
    setUserHasEdited(true);
    userHasEditedRef.current = true;
  };

  const handleDeleteStep = (idx: number) => {
    markUserEdited();
    setEvents((prev) => {
      const nextEvents = prev.filter((_, i) => i !== idx);
      lastServerCountRef.current = nextEvents.length;
      if (session) {
        void syncRecorderSession(session.session_id, nextEvents).catch((err) => {
          console.debug("Failed to sync deleted step to server:", err);
        });
      }
      return nextEvents;
    });
    if (editingIdx === idx) {
      setEditingIdx(null);
      setEditDraft(null);
    } else if (editingIdx !== null && editingIdx > idx) {
      setEditingIdx(editingIdx - 1);
    }
  };

  const handleStartEdit = (idx: number) => {
    const target = events[idx];
    if (!target) return;
    setEditingIdx(idx);
    setEditDraft({ ...target });
  };

  const handleSaveEdit = (idx: number) => {
    if (!editDraft) return;
    markUserEdited();
    setEvents((prev) => {
      const next = [...prev];
      next[idx] = editDraft;
      if (session) {
        void syncRecorderSession(session.session_id, next).catch((err) => {
          console.debug("Failed to sync edited step to server:", err);
        });
      }
      return next;
    });
    setEditingIdx(null);
    setEditDraft(null);
  };

  const handleCancelEdit = () => {
    setEditingIdx(null);
    setEditDraft(null);
  };

  const handleMoveStep = (idx: number, direction: "up" | "down") => {
    const targetIdx = direction === "up" ? idx - 1 : idx + 1;
    if (targetIdx < 0 || targetIdx >= events.length) return;
    markUserEdited();
    setEvents((prev) => {
      const next = [...prev];
      const moved = next[idx];
      if (!moved) return prev;
      next.splice(idx, 1);
      next.splice(targetIdx, 0, moved);
      if (session) {
        void syncRecorderSession(session.session_id, next).catch((err) => {
          console.debug("Failed to sync moved step to server:", err);
        });
      }
      return next;
    });
    if (editingIdx === idx) {
      setEditingIdx(targetIdx);
    }
  };

  const handleAddStep = () => {
    markUserEdited();
    const newStep: RecorderCapturedEvent = {
      kind: "click",
      selector: "",
      timestamp: new Date().toISOString(),
    };
    const nextIdx = events.length;
    setEvents((prev) => [...prev, newStep]);
    setEditingIdx(nextIdx);
    setEditDraft(newStep);
  };

  const handleCleanNoise = () => {
    if (events.length <= 1) return;
    const cleaned = coalesceEvents(events);
    userHasEditedRef.current = true;
    setUserHasEdited(true);
    setEvents(cleaned);
    lastServerCountRef.current = cleaned.length;
    if (session) {
      void syncRecorderSession(session.session_id, cleaned).catch((err) => {
        console.debug("Failed to sync cleaned events to server:", err);
      });
    }
  };

  const handleResetToBrowser = async () => {
    if (!session) return;
    setUserHasEdited(false);
    userHasEditedRef.current = false;
    lastServerCountRef.current = 0;
    setEditingIdx(null);
    setEditDraft(null);
    try {
      const detail = await getRecorderSession(session.session_id);
      const rawEvents = detail.captured_events ?? [];
      lastServerCountRef.current = rawEvents.length;
      const firstEvent = rawEvents[0];
      const hasNav = Boolean(
        firstEvent &&
          firstEvent.kind === "navigate" &&
          firstEvent.url &&
          !firstEvent.url.startsWith("about:"),
      );
      const targetUrl = startUrl.startsWith("http") ? startUrl : `https://${startUrl}`;
      const initialEvents =
        !hasNav && startUrl
          ? [
              {
                kind: "navigate" as const,
                url: targetUrl,
                timestamp: new Date().toISOString(),
              },
              ...rawEvents,
            ]
          : rawEvents;
      setEvents(coalesceEvents(initialEvents));
    } catch {
      // ignore
    }
  };

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
      <div className="flex flex-col gap-3" data-testid="gen-recorder-start-panel">
        {status === "running" ? (
          <div
            data-testid="gen-recorder-loading"
            className="flex items-center gap-3 rounded-md border border-accent/30 bg-accent/10 p-3 text-[12px] text-fg-1"
          >
            <Loader2 className="h-4 w-4 animate-spin text-accent shrink-0" aria-hidden="true" />
            <div className="flex flex-col gap-0.5">
              <span className="font-medium text-fg-1">Summoning browser session…</span>
              <span className="text-[11px] text-fg-3">
                Launching Chrome with native CDP event bridge. The browser window will appear shortly.
              </span>
            </div>
          </div>
        ) : (
          <p className="text-[12px] text-fg-3">
            Opens a live browser session. Interact with the page (click, type, navigate), review and edit captured
            steps if needed, then finalize into a test case.
          </p>
        )}
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
          <div data-testid="gen-error" className="rounded-md border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
            {errorMsg ?? "Could not start the recorder."}
          </div>
        ) : null}
      </div>
    );
  }


  return (
    <div className="flex flex-col gap-3 min-w-0" data-testid="gen-recorder-live-panel">
      <div className="flex items-center justify-between text-[12px] text-fg-3">
        <div className="flex items-center gap-2">
          <CircleDot className="h-3.5 w-3.5 animate-pulse text-red" aria-hidden="true" />
          <span>
            Recording — session{" "}
            <span className="font-mono text-[11px] text-fg-4">{session.session_id}</span>
          </span>
        </div>
        <span className="rounded bg-red/10 px-2 py-0.5 text-[11px] font-semibold text-red">
          {events.length} {events.length === 1 ? "step" : "steps"}
        </span>
      </div>

      {browserClosed ? (
        hudFinished ? (
          <div
            data-testid="gen-recorder-resume-banner"
            className="flex flex-col gap-2.5 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-[12px] text-emerald-200"
          >
            <div className="flex items-center gap-2 font-medium text-emerald-300">
              <Check className="h-4 w-4 shrink-0 text-emerald-400" aria-hidden="true" />
              <span>Recording Completed from Browser — Ready for Review</span>
            </div>
            <p className="text-[11px] text-fg-3">
              {events.length} step{events.length === 1 ? "" : "s"} captured and safely saved. Review or edit your test steps below.
              You can finalize directly into a test case, or resume recording if you need to capture additional actions.
            </p>
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              <Button
                type="button"
                size="sm"
                data-testid="recorder-finalize-btn"
                onClick={() => onFinalize(events)}
                className="gap-1.5 bg-emerald-600 hover:bg-emerald-500 text-white font-medium"
              >
                <Check className="h-3.5 w-3.5" />
                Finalize → Create Case ({events.length})
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="recorder-resume-btn"
                disabled={resuming}
                onClick={() => void handleResumeBrowser()}
                className="gap-1.5 border-emerald-500/40 text-emerald-300 hover:bg-emerald-500/10"
              >
                {resuming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                {resuming ? "Re-opening browser…" : "+ Resume Recording"}
              </Button>
            </div>
          </div>
        ) : (
          <div
            data-testid="gen-recorder-resume-banner"
            className="flex flex-col gap-2.5 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-[12px] text-amber-200"
          >
            <div className="flex items-center gap-2 font-medium text-amber-300">
              <AlertTriangle className="h-4 w-4 shrink-0 text-amber-400" aria-hidden="true" />
              <span>Browser Window Disconnected / Closed</span>
            </div>
            <p className="text-[11px] text-fg-3">
              {events.length} action{events.length === 1 ? "" : "s"} captured so far are safely preserved.
              You can re-open the browser to continue recording from the last page, or finalize into a test case now.
            </p>
            <div className="flex items-center gap-2 pt-1 flex-wrap">
              <Button
                type="button"
                size="sm"
                data-testid="recorder-resume-btn"
                disabled={resuming}
                onClick={() => void handleResumeBrowser()}
                className="gap-1.5 bg-amber-600 hover:bg-amber-500 text-white font-medium"
              >
                {resuming ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Play className="h-3.5 w-3.5" />}
                {resuming ? "Re-opening browser…" : "Re-open & Resume Browser"}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="outline"
                data-testid="recorder-finalize-btn"
                onClick={() => onFinalize(events)}
                className="gap-1.5"
              >
                <Check className="h-3.5 w-3.5 text-accent" />
                Finalize Now ({events.length})
              </Button>
            </div>
          </div>
        )
      ) : session.is_headed ? (
        <div
          data-testid="gen-recorder-headed-banner"
          className="flex items-center gap-2.5 rounded-md border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-[12px] text-emerald-400"
        >
          <span className="relative flex h-2.5 w-2.5 shrink-0">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2.5 w-2.5 bg-emerald-500"></span>
          </span>
          <div className="flex-1">
            <strong>Native Browser Window Active:</strong> Interact directly with the target site in the opened Chrome window. Clicks, typing, and navigations are captured live below.
          </div>
        </div>
      ) : (
        <p className="text-[11px] text-fg-4">
          Playwright Codegen session active. Actions performed in the browser are captured into test steps.
        </p>
      )}

      <div className="flex items-center gap-2 flex-wrap">
        {startUrl ? (
          <a
            href={startUrl.startsWith("http") ? startUrl : `https://${startUrl}`}
            target="_blank"
            rel="noreferrer"
            data-testid="gen-recorder-target-link"
            className="text-[12px] text-fg-3 hover:text-fg-1 underline ml-auto"
            title="Open direct target site in a new tab"
          >
            Open Target Site ↗
          </a>
        ) : null}
      </div>

      {/* Captured steps list with pre-finalize editor */}
      <div className="flex flex-col gap-2 rounded-md border border-edge-subtle bg-bg-2 p-2.5 min-w-0">
        <div className="flex items-center justify-between gap-2 flex-wrap sm:flex-nowrap">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-[11px] font-medium text-fg-4 uppercase tracking-wider shrink-0">
              Captured Steps ({events.length})
            </span>
            {userHasEdited ? (
              <span
                data-testid="gen-recorder-customized-badge"
                className="rounded border border-amber/40 bg-amber/10 px-1.5 py-0.5 text-[10px] text-amber font-mono shrink-0"
              >
                Customized (live sync active)
              </span>
            ) : null}
          </div>
          <div className="flex items-center gap-1.5 shrink-0 ml-auto">
            {events.length > 2 ? (
              <Button
                type="button"
                size="xs"
                variant="ghost"
                data-testid="gen-recorder-clean-noise"
                onClick={handleCleanNoise}
                className="h-6 gap-1 text-[11px] text-fg-3 hover:text-accent"
                title="Deduplicate rapid clicks and clicks preceding input typing"
              >
                <Sparkles className="h-3 w-3 text-accent" />
                Clean noise
              </Button>
            ) : null}
            {userHasEdited ? (
              <Button
                type="button"
                size="xs"
                variant="ghost"
                data-testid="gen-recorder-reset-sync"
                onClick={() => void handleResetToBrowser()}
                className="h-6 gap-1 text-[11px] text-fg-3 hover:text-fg-1"
              >
                <RefreshCw className="h-3 w-3" />
                Reset from browser
              </Button>
            ) : null}
            <Button
              type="button"
              size="xs"
              variant="outline"
              data-testid="gen-recorder-add-step"
              onClick={handleAddStep}
              className="h-6 gap-1 text-[11px]"
            >
              <Plus className="h-3 w-3" />
              Add step
            </Button>
          </div>
        </div>

        {events.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-6 text-center gap-1.5">
            <div className="flex items-center gap-2 text-fg-3">
              <Compass className="h-4 w-4 animate-spin text-accent/80" />
              <span className="text-[12px] font-medium text-fg-2">Listening for browser interactions…</span>
            </div>
            <p className="text-[11px] text-fg-4 max-w-sm">
              Navigate, click elements, or type into form inputs in the browser window. Captured events will appear here in real time.
            </p>
          </div>
        ) : (
          <div className="max-h-72 overflow-y-auto overflow-x-hidden space-y-1.5 pr-1 font-mono text-[11px]">
            {events.map((evt, idx) =>
              editingIdx === idx && editDraft ? (
                <div
                  key={`rec-edit-${idx}`}
                  data-testid={`gen-recorder-step-edit-${idx}`}
                  className="flex flex-col gap-2 rounded bg-bg-elev-2 p-2.5 border border-accent/40 text-fg-1 min-w-0"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-[11px] font-mono font-semibold text-accent">
                        Step {idx + 1}
                      </span>
                      <select
                        data-testid="gen-step-edit-kind"
                        value={editDraft.kind}
                        onChange={(e) =>
                          setEditDraft({
                            ...editDraft,
                            kind: e.target.value as "navigate" | "click" | "type" | "assert" | "select" | "upload",
                          })
                        }
                        className="h-6 rounded border border-border bg-bg-elev-1 px-1.5 font-mono text-[11px] text-fg-1 focus:outline-none focus:ring-1 focus:ring-accent/40"
                      >
                        <option value="navigate">NAVIGATE</option>
                        <option value="click">CLICK</option>
                        <option value="type">TYPE</option>
                        <option value="select">SELECT</option>
                        <option value="upload">UPLOAD</option>
                        <option value="assert">ASSERT</option>
                      </select>
                    </div>
                  </div>

                  {editDraft.kind === "navigate" ? (
                    <div className="flex flex-col gap-1">
                      <Label className="text-[10.5px] text-fg-4">Target URL</Label>
                      <Input
                        data-testid="gen-step-edit-url"
                        value={editDraft.url ?? ""}
                        placeholder="https://example.com"
                        onChange={(e) => setEditDraft({ ...editDraft, url: e.target.value })}
                        className="h-7 text-[11.5px]"
                      />
                    </div>
                  ) : null}

                  {editDraft.kind === "click" || editDraft.kind === "type" || editDraft.kind === "select" || editDraft.kind === "upload" ? (
                    <div className="flex flex-col gap-1">
                      <Label className="text-[10.5px] text-fg-4">CSS / Attribute Selector</Label>
                      <Input
                        data-testid="gen-step-edit-selector"
                        value={editDraft.selector ?? ""}
                        placeholder='[data-test="username"] or button#login'
                        onChange={(e) => setEditDraft({ ...editDraft, selector: e.target.value })}
                        className="h-7 font-mono text-[11px]"
                      />
                    </div>
                  ) : null}

                  {editDraft.kind === "type" ? (
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 items-center">
                      <div className="col-span-2 flex flex-col gap-1">
                        <div className="flex items-center justify-between">
                          <Label className="text-[10.5px] text-fg-4">Input Text</Label>
                          <button
                            type="button"
                            data-testid="gen-step-make-variable"
                            onClick={() => {
                              const curr = editDraft.text ?? "";
                              if (curr) {
                                setEditDraft({ ...editDraft, text: toDynamicVariableTemplate(curr) });
                              }
                            }}
                            className="text-[10px] text-accent hover:underline flex items-center gap-0.5"
                          >
                            <Sparkles className="h-2.5 w-2.5" />
                            Make variable
                          </button>
                        </div>
                        <Input
                          data-testid="gen-step-edit-text"
                          value={editDraft.text ?? ""}
                          placeholder="Value to enter"
                          onChange={(e) => setEditDraft({ ...editDraft, text: e.target.value })}
                          className="h-7 text-[11.5px]"
                        />
                      </div>
                      <label className="flex items-center gap-1.5 text-[11px] text-fg-3 pt-3.5 cursor-pointer">
                        <input
                          data-testid="gen-step-edit-masked"
                          type="checkbox"
                          checked={Boolean(editDraft.masked)}
                          onChange={(e) => setEditDraft({ ...editDraft, masked: e.target.checked })}
                          className="rounded border-border text-accent"
                        />
                        <span>Mask secret</span>
                      </label>
                      <div className="col-span-3">
                        <span className="text-[10px] text-fg-4">
                          {editDraft.masked
                            ? "Masked secrets are stored as {{password}} and resolved via SUITEST_PASSWORD env var during execution. Uncheck to store plaintext credentials."
                            : "Plaintext input is stored directly in the test case and used during execution."}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  {editDraft.kind === "select" ? (
                    <div className="flex flex-col gap-1">
                      <Label className="text-[10.5px] text-fg-4">Selected Option Value</Label>
                      <Input
                        value={editDraft.text ?? ""}
                        placeholder="Option value"
                        onChange={(e) => setEditDraft({ ...editDraft, text: e.target.value })}
                        className="h-7 text-[11.5px]"
                      />
                    </div>
                  ) : null}

                  {editDraft.kind === "upload" ? (
                    <div className="flex flex-col gap-1">
                      <Label className="text-[10.5px] text-fg-4">File Name / Fixture</Label>
                      <Input
                        value={editDraft.text ?? ""}
                        placeholder="e.g. document.pdf"
                        onChange={(e) => setEditDraft({ ...editDraft, text: e.target.value })}
                        className="h-7 text-[11.5px]"
                      />
                    </div>
                  ) : null}

                  {editDraft.kind === "assert" ? (
                    <div className="flex flex-col gap-1">
                      <Label className="text-[10.5px] text-fg-4">Expected Condition</Label>
                      <Input
                        data-testid="gen-step-edit-assertion"
                        value={String(editDraft.assertion?.expected ?? "")}
                        placeholder="Page title or element is visible"
                        onChange={(e) =>
                          setEditDraft({
                            ...editDraft,
                            assertion: { ...(editDraft.assertion ?? {}), expected: e.target.value },
                          })
                        }
                        className="h-7 text-[11.5px]"
                      />
                    </div>
                  ) : null}

                  <div className="flex items-center justify-end gap-1.5 pt-1">
                    <Button
                      type="button"
                      size="xs"
                      variant="ghost"
                      data-testid="gen-step-edit-cancel"
                      onClick={handleCancelEdit}
                    >
                      Cancel
                    </Button>
                    <Button
                      type="button"
                      size="xs"
                      variant="outline"
                      data-testid="gen-step-edit-save"
                      onClick={() => handleSaveEdit(idx)}
                    >
                      Save step
                    </Button>
                  </div>
                </div>
              ) : (
                <div
                  key={`rec-step-${idx}-${evt.kind}-${evt.timestamp ?? idx}`}
                  data-testid={`gen-recorder-step-${idx}`}
                  className="group flex items-center justify-between gap-2 rounded bg-bg-1 px-2 py-1.5 border border-edge-subtle text-fg-2 hover:border-fg-4/30 transition-colors min-w-0"
                >
                  <div className="flex items-center gap-2 min-w-0 flex-1 overflow-hidden">
                    <span className="text-[10px] text-fg-4 w-4 shrink-0 text-right">{idx + 1}</span>
                    {evt.kind === "navigate" ? (
                      <>
                        <Compass className="h-3.5 w-3.5 shrink-0 text-cyan-400" />
                        <span className="text-cyan-400 font-semibold text-[10px] shrink-0">NAV</span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={evt.url ?? ""}>
                          {evt.url}
                        </span>
                      </>
                    ) : evt.kind === "click" ? (
                      <>
                        <MousePointerClick className="h-3.5 w-3.5 shrink-0 text-emerald-400" />
                        <span className="text-emerald-400 font-semibold text-[10px] shrink-0">CLICK</span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={evt.selector ?? ""}>
                          {evt.selector}
                        </span>
                      </>
                    ) : evt.kind === "type" ? (
                      <>
                        <Keyboard className="h-3.5 w-3.5 shrink-0 text-amber-400" />
                        <span className="text-amber-400 font-semibold text-[10px] shrink-0">TYPE</span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={`${evt.selector ?? ""} = ${evt.masked ? "••••••" : evt.text ?? ""}`}>
                          {evt.selector} = {evt.masked ? "••••••" : evt.text}
                        </span>
                      </>
                    ) : evt.kind === "select" ? (
                      <>
                        <ListFilter className="h-3.5 w-3.5 shrink-0 text-sky-400" />
                        <span className="text-sky-400 font-semibold text-[10px] shrink-0">SELECT</span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={`${evt.selector ?? ""} → ${String(evt.assertion?.label ?? evt.text ?? "")}`}>
                          {evt.selector} → {String(evt.assertion?.label ?? evt.text ?? "")}
                        </span>
                      </>
                    ) : evt.kind === "upload" ? (
                      <>
                        <Upload className="h-3.5 w-3.5 shrink-0 text-pink-400" />
                        <span className="text-pink-400 font-semibold text-[10px] shrink-0">UPLOAD</span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={`${evt.selector ?? ""} ← ${evt.text || String((evt as { data?: { file_name?: string } }).data?.file_name ?? "file")}`}>
                          {evt.selector} ← {evt.text || String((evt as { data?: { file_name?: string } }).data?.file_name ?? "file")}
                        </span>
                      </>
                    ) : (
                      <>
                        <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-purple-400" />
                        <span className="text-purple-400 font-semibold text-[10px] shrink-0">
                          {evt.kind.toUpperCase()}
                        </span>
                        <span className="truncate text-fg-3 text-[11px] min-w-0" title={String(evt.assertion?.description ?? evt.assertion?.expected ?? evt.selector ?? "")}>
                          {String(evt.assertion?.description ?? evt.assertion?.expected ?? evt.selector ?? "")}
                        </span>
                      </>
                    )}
                  </div>
                  <div className="flex items-center gap-0.5 shrink-0 opacity-80 group-hover:opacity-100">
                    <button
                      type="button"
                      disabled={idx === 0}
                      onClick={() => handleMoveStep(idx, "up")}
                      className="p-1 text-fg-4 hover:text-fg-1 disabled:opacity-20 disabled:pointer-events-none rounded hover:bg-bg-elev-2"
                      title="Move step up"
                      aria-label="Move step up"
                    >
                      <ArrowUp className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      disabled={idx === events.length - 1}
                      onClick={() => handleMoveStep(idx, "down")}
                      className="p-1 text-fg-4 hover:text-fg-1 disabled:opacity-20 disabled:pointer-events-none rounded hover:bg-bg-elev-2"
                      title="Move step down"
                      aria-label="Move step down"
                    >
                      <ArrowDown className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      data-testid={`gen-recorder-step-edit-btn-${idx}`}
                      onClick={() => handleStartEdit(idx)}
                      className="p-1 text-fg-4 hover:text-accent rounded hover:bg-bg-elev-2"
                      title="Edit step"
                      aria-label="Edit step"
                    >
                      <Pencil className="h-3 w-3" />
                    </button>
                    <button
                      type="button"
                      data-testid={`gen-recorder-step-delete-btn-${idx}`}
                      onClick={() => handleDeleteStep(idx)}
                      className="p-1 text-fg-4 hover:text-red rounded hover:bg-bg-elev-2"
                      title="Delete step"
                      aria-label="Delete step"
                    >
                      <Trash2 className="h-3 w-3" />
                    </button>
                  </div>
                </div>
              ),
            )}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between pt-1">
        <Button
          type="button"
          size="sm"
          data-testid="gen-recorder-finalize"
          disabled={status === "running" || caseName.trim().length === 0}
          onClick={() => onFinalize(events)}
          className="self-start"
        >
          {status === "running" ? "Finalizing…" : "Finalize → create case"}
        </Button>
      </div>

      {status === "error" ? (
        <div data-testid="gen-error" className="rounded-md border border-red/40 bg-red/10 px-3 py-2 text-[12px] text-red">
          {errorMsg ?? "Could not finalize recording."}
        </div>
      ) : null}
    </div>
  );
}
