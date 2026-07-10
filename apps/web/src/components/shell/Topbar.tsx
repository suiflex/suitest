import { useMatches, useNavigate } from "@tanstack/react-router";
import {
  BarChart3,
  BookOpen,
  Bug,
  FileCode2,
  HelpCircle,
  Inbox,
  LayoutDashboard,
  Menu,
  Network,
  Play,
  Plug,
  Plus,
  Search,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { LanguageSwitcher } from "@/components/shell/LanguageSwitcher";
import { ThemeToggle } from "@/components/shell/ThemeToggle";
import { TierBadge } from "@/components/shared/TierBadge";
import { Button } from "@/components/ui/button";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

interface CommandTarget {
  label: string;
  to: string;
  icon: LucideIcon;
}

const COMMAND_TARGETS: ReadonlyArray<CommandTarget> = [
  { label: "Go to Dashboard", to: "/dashboard", icon: LayoutDashboard },
  { label: "Go to Test Cases", to: "/cases", icon: FileCode2 },
  { label: "Go to Test Runs", to: "/runs", icon: Play },
  { label: "Go to Defects", to: "/defects", icon: Bug },
  { label: "Go to Analytics", to: "/analytics", icon: BarChart3 },
  { label: "Go to Traceability", to: "/trace", icon: Network },
  { label: "Go to Integrations", to: "/integrations", icon: Plug },
  { label: "Go to Docs", to: "/docs", icon: BookOpen },
  { label: "Go to Inbox", to: "/inbox", icon: Inbox },
];

export interface TopbarProps {
  /** External docs link opened by the help icon. */
  helpHref?: string;
  /** Opens the mobile sidebar drawer (< md). Hamburger hidden when omitted. */
  onMenuClick?: () => void;
}

/**
 * Persistent top bar (47px). Breadcrumbs left, search palette + tier badge +
 * actions on the right. `+ New` is intentionally disabled in M1b — authoring
 * tools arrive in M1d.
 */
export function Topbar({
  helpHref = "https://github.com/suitest/docs",
  onMenuClick,
}: TopbarProps = {}): React.ReactElement {
  const [commandOpen, setCommandOpen] = useState(false);
  const navigate = useNavigate();

  // Build breadcrumbs from every route match that declares a title in its
  // `staticData`. The root + `_app` pathless layout are intentionally
  // excluded — they don't carry a title.
  const breadcrumbs = useMatches({
    select: (matches) =>
      matches
        .map((m) => m.staticData.title)
        .filter((t): t is string => typeof t === "string" && t.length > 0),
  });

  // Global ⌘K / Ctrl+K shortcut. Re-bound on each render is cheap because
  // there's only one Topbar mounted in the shell.
  useEffect(() => {
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setCommandOpen((prev) => !prev);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const runCommand = useCallback(
    (to: string) => {
      setCommandOpen(false);
      void navigate({ to });
    },
    [navigate],
  );

  return (
    <header
      className="flex h-[47px] items-center gap-3 border-b border-border-subtle bg-bg-base px-4"
      data-testid="topbar"
    >
      {/* Mobile — sidebar drawer trigger */}
      {onMenuClick ? (
        <button
          type="button"
          onClick={onMenuClick}
          aria-label="Open navigation"
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1 md:hidden"
          data-testid="topbar-menu-button"
        >
          <Menu className="h-4 w-4" aria-hidden="true" />
        </button>
      ) : null}

      {/* Left — Breadcrumbs */}
      <Breadcrumbs segments={breadcrumbs} />

      <div className="ml-auto flex shrink-0 items-center gap-2">
        {/* Search palette trigger — full field ≥ sm, icon-only below */}
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          className="hidden h-7 w-[160px] items-center gap-2 rounded-md border border-border bg-bg-elev-1 px-2 text-left text-[12.5px] text-fg-4 hover:bg-bg-elev-2 sm:inline-flex lg:w-[220px]"
          data-testid="topbar-search-trigger"
        >
          <Search className="h-3.5 w-3.5" aria-hidden="true" />
          <span className="flex-1">Search…</span>
          <kbd className="ml-auto inline-flex h-5 items-center gap-0.5 rounded border border-border bg-bg-elev-2 px-1 font-mono text-[10px] text-fg-3">
            <span className="text-[10px]">⌘</span>K
          </kbd>
        </button>
        <button
          type="button"
          onClick={() => setCommandOpen(true)}
          aria-label="Search"
          className="flex h-7 w-7 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1 sm:hidden"
          data-testid="topbar-search-trigger-mobile"
        >
          <Search className="h-4 w-4" aria-hidden="true" />
        </button>

        {/* Language switcher (M4-12) */}
        <LanguageSwitcher />

        {/* Dark / light theme toggle */}
        <ThemeToggle />

        {/* Help icon */}
        <a
          href={helpHref}
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Help"
          className="flex h-7 w-7 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          data-testid="topbar-help-link"
        >
          <HelpCircle className="h-4 w-4" aria-hidden="true" />
        </a>

        <TierBadge />

        {/* + New (disabled in M1b) */}
        <TooltipProvider delayDuration={150}>
          <Tooltip>
            <TooltipTrigger asChild>
              {/* Wrapping span lets the tooltip fire even when the underlying
                  button is disabled (pointer-events:none on disabled). */}
              <span tabIndex={0} data-testid="topbar-new-wrapper">
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled
                  className="gap-1 border-border bg-bg-elev-1 text-fg-3"
                  data-testid="topbar-new-button"
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden="true" />
                  New
                </Button>
              </span>
            </TooltipTrigger>
            <TooltipContent>Authoring tools enabled in M1d</TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>

      <CommandDialog
        open={commandOpen}
        onOpenChange={setCommandOpen}
        title="Command palette"
        description="Jump to a screen"
      >
        <CommandInput placeholder="Type a command or search…" />
        <CommandList data-testid="topbar-command-list">
          <CommandEmpty>No results.</CommandEmpty>
          <CommandGroup heading="Navigate">
            {COMMAND_TARGETS.map((target) => {
              const Icon = target.icon;
              return (
                <CommandItem
                  key={target.to}
                  value={target.label}
                  onSelect={() => runCommand(target.to)}
                  data-testid={`command-item-${target.to.replace(/\//g, "")}`}
                >
                  <Icon className="h-4 w-4" aria-hidden="true" />
                  <span>{target.label}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        </CommandList>
      </CommandDialog>
    </header>
  );
}

function Breadcrumbs({ segments }: { segments: ReadonlyArray<string> }): React.ReactElement {
  if (segments.length === 0) {
    return <div data-testid="topbar-breadcrumbs" className="text-[13px] text-fg-3" />;
  }
  return (
    <ol
      className="flex min-w-0 items-center gap-1.5 overflow-hidden whitespace-nowrap text-[13px]"
      aria-label="Breadcrumbs"
      data-testid="topbar-breadcrumbs"
    >
      {segments.map((seg, idx) => {
        const last = idx === segments.length - 1;
        return (
          <li key={`${seg}-${idx.toString()}`} className="flex min-w-0 items-center gap-1.5">
            {idx > 0 ? (
              <span className="text-fg-5" aria-hidden="true">
                ›
              </span>
            ) : null}
            <span className={cn("truncate", last ? "font-medium text-fg-1" : "text-fg-3")}>
              {seg}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
