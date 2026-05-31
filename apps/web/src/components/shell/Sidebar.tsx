import { Link } from "@tanstack/react-router";
import {
  BarChart3,
  Bell,
  BookOpen,
  Bug,
  ChevronDown,
  FileCode2,
  Inbox,
  LayoutDashboard,
  Network,
  Play,
  Plug,
  Settings,
  Shield,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";

import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn } from "@/lib/utils";

interface NavItem {
  label: string;
  icon: LucideIcon;
  to: string;
  badgeCount?: number;
  liveDot?: boolean;
  disabled?: boolean;
}

interface NavGroup {
  eyebrow: string;
  items: NavItem[];
}

export interface SidebarProps {
  /** Display name of the active workspace. */
  workspaceName?: string;
  /** Display name of the signed-in user. */
  userName?: string;
  /** Role label shown next to the user name in the footer. */
  userRole?: string;
  /** Number of unread notifications. >0 renders a red dot over the bell. */
  unreadCount?: number;
  /** Inbox unread item count. >0 renders a badge next to "Inbox". */
  inboxCount?: number;
  /** Active test runs count. >0 renders a pulsing live dot next to "Test Runs". */
  activeRunsCount?: number;
  /** Read-only list of workspaces for the picker popover. */
  workspaces?: ReadonlyArray<{ id: string; name: string }>;
  /** Show the super-admin "Admin" nav item (M1e). */
  isSuperuser?: boolean;
}

/**
 * Persistent left rail (224px). Brand + workspace + nav + user footer.
 *
 * Capability-agnostic — every nav target is deterministic-first, so the
 * sidebar renders identically in ZERO / LOCAL / CLOUD tiers. AI surfaces
 * are gated inside the AiPanel + per-screen feature flags, not here.
 */
export function Sidebar({
  workspaceName = "Acme QA",
  userName = "Maya",
  userRole = "Owner",
  unreadCount = 0,
  inboxCount = 0,
  activeRunsCount = 0,
  workspaces = [{ id: "default", name: "Acme QA" }],
  isSuperuser = false,
}: SidebarProps): React.ReactElement {
  const [pickerOpen, setPickerOpen] = useState(false);

  const configItems: NavItem[] = [
    { label: "Integrations", icon: Plug, to: "/integrations" },
    { label: "Docs", icon: BookOpen, to: "/docs" },
    { label: "Settings", icon: Settings, to: "/settings" },
  ];
  if (isSuperuser) {
    configItems.push({ label: "Admin", icon: Shield, to: "/admin" });
  }

  const groups: NavGroup[] = [
    {
      eyebrow: "Workspace",
      items: [
        { label: "Dashboard", icon: LayoutDashboard, to: "/dashboard" },
        { label: "Inbox", icon: Inbox, to: "/inbox", badgeCount: inboxCount },
      ],
    },
    {
      eyebrow: "Testing",
      items: [
        { label: "Test Cases", icon: FileCode2, to: "/cases" },
        {
          label: "Test Runs",
          icon: Play,
          to: "/runs",
          liveDot: activeRunsCount > 0,
        },
        { label: "Defects", icon: Bug, to: "/defects" },
      ],
    },
    {
      eyebrow: "Insights",
      items: [
        { label: "Analytics", icon: BarChart3, to: "/analytics" },
        { label: "Traceability", icon: Network, to: "/trace" },
      ],
    },
    {
      eyebrow: "Config",
      items: configItems,
    },
  ];

  return (
    <aside
      className="flex h-screen w-[224px] flex-col border-r border-border-subtle bg-bg-elev-1"
      data-testid="sidebar"
    >
      {/* Section 1 — Brand */}
      <div className="flex h-[47px] items-center justify-between border-b border-border-subtle px-4">
        <span className="select-none font-mono text-[15px] font-bold tracking-tight">
          sui<span className="text-accent">test</span>
        </span>
        <button
          type="button"
          aria-label="Notifications"
          className="relative flex h-7 w-7 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          data-testid="sidebar-bell"
        >
          <Bell className="h-4 w-4" aria-hidden="true" />
          {unreadCount > 0 ? (
            <span
              data-testid="sidebar-bell-unread"
              className="absolute right-1 top-1 h-1.5 w-1.5 rounded-full bg-red"
              aria-label={`${unreadCount} unread`}
            />
          ) : null}
        </button>
      </div>

      {/* Section 2 — Workspace picker */}
      <div className="border-b border-border-subtle px-3 py-3">
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-bg-elev-2"
              data-testid="workspace-picker"
            >
              <span
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-elev-3 font-mono text-[11px] font-semibold text-fg-1"
                aria-hidden="true"
              >
                {workspaceName.slice(0, 2).toUpperCase()}
              </span>
              <span className="flex-1 truncate text-[12.5px] font-medium text-fg-1">
                {workspaceName}
              </span>
              <ChevronDown className="h-3.5 w-3.5 shrink-0 text-fg-4" aria-hidden="true" />
            </button>
          </PopoverTrigger>
          <PopoverContent
            align="start"
            className="w-[200px] border-border bg-bg-elev-1 p-1 text-fg-1"
          >
            <ul className="space-y-0.5" data-testid="workspace-picker-list">
              {workspaces.map((ws) => (
                <li key={ws.id}>
                  <div
                    className={cn(
                      "rounded-sm px-2 py-1.5 text-[12.5px]",
                      ws.name === workspaceName ? "bg-bg-elev-2 text-fg-1" : "text-fg-3",
                    )}
                  >
                    {ws.name}
                  </div>
                </li>
              ))}
            </ul>
            <p className="mt-2 px-2 text-[11px] uppercase tracking-[0.07em] text-fg-5">
              Switching arrives in M1c
            </p>
          </PopoverContent>
        </Popover>
      </div>

      {/* Section 3 — Nav */}
      <ScrollArea className="flex-1">
        <nav className="px-2 py-3" aria-label="Primary">
          {groups.map((group) => (
            <div key={group.eyebrow} className="mb-4 last:mb-0">
              <div className="mb-1.5 px-2 text-[11px] font-medium uppercase tracking-[0.07em] text-fg-5">
                {group.eyebrow}
              </div>
              <ul className="space-y-0.5">
                {group.items.map((item) => (
                  <li key={item.label}>
                    <SidebarItem item={item} />
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </nav>
      </ScrollArea>

      {/* Section 4 — User footer */}
      <div className="flex items-center gap-2 border-t border-border-subtle px-3 py-3">
        <span
          className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-bg-elev-3 font-mono text-[11px] font-semibold text-fg-1"
          aria-hidden="true"
        >
          {userName.slice(0, 2).toUpperCase()}
        </span>
        <div className="flex-1 overflow-hidden">
          <div className="truncate text-[12.5px] font-medium text-fg-1">{userName}</div>
          <div
            className="mt-0.5 inline-flex h-[15px] items-center rounded-sm bg-bg-elev-3 px-1.5 text-[10px] font-medium uppercase tracking-wide text-fg-3"
            data-testid="user-role-pill"
          >
            {userRole}
          </div>
        </div>
        <Link
          to="/settings"
          aria-label="Settings"
          className="flex h-7 w-7 items-center justify-center rounded-md text-fg-3 hover:bg-bg-elev-2 hover:text-fg-1"
          data-testid="user-settings-link"
        >
          <Settings className="h-4 w-4" aria-hidden="true" />
        </Link>
      </div>
    </aside>
  );
}

function SidebarItem({ item }: { item: NavItem }): React.ReactElement {
  const Icon = item.icon;
  const baseCls =
    "group flex items-center gap-2 rounded-md px-2 py-1.5 text-[12.5px] text-fg-3 transition-colors hover:bg-bg-elev-2 hover:text-fg-1";

  if (item.disabled) {
    return (
      <div
        aria-disabled="true"
        className={cn(baseCls, "cursor-not-allowed text-fg-5 hover:bg-transparent hover:text-fg-5")}
        data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
        data-disabled="true"
      >
        <Icon className="h-3.5 w-3.5 shrink-0 text-fg-5" aria-hidden="true" />
        <span className="flex-1 truncate">{item.label}</span>
      </div>
    );
  }

  return (
    <Link
      to={item.to}
      className={baseCls}
      activeProps={{
        className: cn(baseCls, "bg-bg-elev-2 text-fg-1 [&_svg]:text-accent"),
      }}
      data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}`}
    >
      <Icon className="h-3.5 w-3.5 shrink-0 text-fg-4" aria-hidden="true" />
      <span className="flex-1 truncate">{item.label}</span>
      {item.badgeCount !== undefined && item.badgeCount > 0 ? (
        <span
          className="flex h-4 min-w-[16px] items-center justify-center rounded-full bg-bg-elev-3 px-1 font-mono text-[10px] font-semibold text-fg-3"
          data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}-badge`}
        >
          {item.badgeCount}
        </span>
      ) : null}
      {item.liveDot ? (
        <span
          className="h-1.5 w-1.5 rounded-full bg-accent suitest-pulse"
          data-testid={`nav-${item.label.toLowerCase().replace(/\s+/g, "-")}-live-dot`}
          aria-label="active runs"
        />
      ) : null}
    </Link>
  );
}
