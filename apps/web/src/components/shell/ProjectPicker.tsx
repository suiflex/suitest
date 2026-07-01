import { useQuery } from "@tanstack/react-query";
import { Check, ChevronDown, FolderKanban } from "lucide-react";
import { useState } from "react";

import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { api } from "@/lib/api-client";
import type { components } from "@/lib/api-types";
import { cn } from "@/lib/utils";
import { useActiveProject } from "@/stores/use-active-project";

type Project = components["schemas"]["ProjectPublic"];
type ProjectsPage = { items: Project[] };

/**
 * Project switcher — Test Cases / Test Runs / Analytics are all scoped to the
 * active project (`useActiveProject`). A workspace can hold several projects
 * (e.g. a backend + a frontend suite), so without this switcher only the first
 * project's data is ever visible. Sits under the workspace picker in the sidebar.
 */
export function ProjectPicker(): React.ReactElement | null {
  const [open, setOpen] = useState(false);
  const projectId = useActiveProject((s) => s.projectId);
  const setProjectId = useActiveProject((s) => s.setProjectId);

  const { data } = useQuery({
    queryKey: ["projects"] as const,
    queryFn: async () => (await api.get<ProjectsPage>("/projects")).data,
  });
  const projects = data?.items ?? [];
  if (projects.length === 0) return null;

  const active = projects.find((p) => p.id === projectId) ?? projects[0];

  return (
    <div className="border-b border-border-subtle px-3 py-2">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <button
            type="button"
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left hover:bg-bg-elev-2"
            data-testid="project-picker"
          >
            <FolderKanban className="h-3.5 w-3.5 shrink-0 text-fg-4" aria-hidden="true" />
            <span className="flex flex-col overflow-hidden">
              <span className="text-[9.5px] uppercase tracking-wide text-fg-5">Project</span>
              <span className="truncate text-[12px] font-medium text-fg-1">
                {active?.name ?? "Select project"}
              </span>
            </span>
            <ChevronDown className="ml-auto h-3.5 w-3.5 shrink-0 text-fg-4" aria-hidden="true" />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-[220px] border-border bg-bg-elev-1 p-1 text-fg-1"
        >
          <ul className="space-y-0.5" data-testid="project-picker-list">
            {projects.map((p) => {
              const isActive = p.id === active?.id;
              return (
                <li key={p.id}>
                  <button
                    type="button"
                    data-testid="project-picker-item"
                    data-active={isActive ? "true" : "false"}
                    onClick={() => {
                      setOpen(false);
                      if (!isActive) setProjectId(p.id);
                    }}
                    className={cn(
                      "flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-[12.5px] hover:bg-bg-elev-2",
                      isActive ? "bg-bg-elev-2 text-fg-1" : "text-fg-3",
                    )}
                  >
                    <span className="flex-1 truncate">{p.name}</span>
                    {isActive ? (
                      <Check className="h-3.5 w-3.5 shrink-0 text-accent" aria-hidden="true" />
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ul>
        </PopoverContent>
      </Popover>
    </div>
  );
}
