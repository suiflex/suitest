import { createFileRoute } from "@tanstack/react-router";
import { formatDistanceToNow } from "date-fns";
import {
  AlertTriangle,
  BookText,
  FileJson,
  Globe,
  type LucideIcon,
  Notebook,
  Plus,
} from "lucide-react";
import { Suspense } from "react";

import { DocsSkeleton } from "@/components/docs/skeleton";
import { DisabledTooltip } from "@/components/shared/DisabledTooltip";
import { EmptyState } from "@/components/shared/EmptyState";
import { ErrorBoundary } from "@/components/shared/ErrorBoundary";
import { Button } from "@/components/ui/button";
import { useDocuments } from "@/hooks/use-documents";
import type { components } from "@/lib/api-types";
import { useCapabilities } from "@/stores/use-capabilities";

type Doc = components["schemas"]["DocumentListItem"];

const KIND_ICON: Record<Doc["kind"], LucideIcon> = {
  PRD: BookText,
  OPENAPI: FileJson,
  URL_CRAWL: Globe,
  LINEAR_ISSUE: Notebook,
  NOTION_PAGE: Notebook,
  CUSTOM: BookText,
};

const KIND_LABEL: Record<Doc["kind"], string> = {
  PRD: "PRD",
  OPENAPI: "OpenAPI",
  URL_CRAWL: "URL crawl",
  LINEAR_ISSUE: "Linear",
  NOTION_PAGE: "Notion",
  CUSTOM: "Custom",
};

/**
 * Pick the indexing label per capability tier (UI_SPEC § 3.11):
 *   - `embeddings_semantic` → "Semantic"
 *   - else if backend reports `fastembed` → "Semantic (fastembed)"
 *   - else → "FTS"
 */
function useIndexingLabel(): string {
  return useCapabilities((s) => {
    const caps = s.capabilities;
    if (!caps) return "FTS";
    if (caps.features.semantic_search) {
      if (caps.embeddings.backend === "fastembed") return "Semantic (fastembed)";
      return "Semantic";
    }
    return "FTS";
  });
}

function DocCard({ doc }: { doc: Doc }): React.ReactElement {
  const indexing = useIndexingLabel();
  const Icon = KIND_ICON[doc.kind];
  const indexedRel =
    doc.indexed_at !== null && doc.indexed_at !== undefined
      ? formatDistanceToNow(new Date(doc.indexed_at), { addSuffix: true })
      : "never";

  return (
    <article
      data-testid="doc-card"
      data-doc-id={doc.id}
      className="flex flex-col gap-2 rounded-md border border-border bg-bg-elev-1 p-4"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <span className="inline-flex h-8 w-8 items-center justify-center rounded-md bg-bg-elev-2 text-fg-3">
            <Icon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="flex flex-col">
            <h3 className="text-[13px] font-semibold text-fg-1">{doc.title}</h3>
            <span className="font-mono text-[10.5px] text-fg-5">{KIND_LABEL[doc.kind]}</span>
          </div>
        </div>
      </div>
      <p className="text-[12px] text-fg-3">
        <span className="font-mono text-fg-4">{doc.chunk_count}</span> chunks ·{" "}
        <span data-testid="doc-indexing-label">{indexing}</span> indexed {indexedRel}
      </p>
      <footer className="flex items-center justify-between border-t border-border pt-2 text-[11.5px] text-fg-5">
        <span className="font-mono">0 test cases generated</span>
        <DisabledTooltip reason="Source CRUD ships in M2">
          <Button type="button" size="sm" variant="outline" disabled>
            Re-sync
          </Button>
        </DisabledTooltip>
      </footer>
    </article>
  );
}

function DocsBody(): React.ReactElement {
  const { data } = useDocuments();
  if (data.items.length === 0) {
    return (
      <EmptyState
        icon={BookText}
        title="No sources connected"
        subtitle="Add a Notion workspace, Confluence space, or OpenAPI spec to power generation."
        action={[{ label: "Add source", variant: "outline" }]}
      />
    );
  }
  return (
    <div className="grid grid-cols-2 gap-3" data-testid="docs-grid">
      {data.items.map((d) => (
        <DocCard key={d.id} doc={d} />
      ))}
    </div>
  );
}

function DocsHeader(): React.ReactElement {
  return (
    <header className="flex items-center justify-between" data-testid="docs-header">
      <h2 className="text-[20px] font-semibold tracking-[-.01em] text-fg-1">Docs & specs</h2>
      <DisabledTooltip reason="Source CRUD ships in M2">
        <Button type="button" size="sm" disabled>
          <Plus className="h-3.5 w-3.5" aria-hidden="true" />
          Add source
        </Button>
      </DisabledTooltip>
    </header>
  );
}

function DocsError({ reset }: { reset: () => void }): React.ReactElement {
  return (
    <EmptyState
      icon={AlertTriangle}
      title="Couldn't load documents"
      action={{ label: "Retry", onClick: reset }}
    />
  );
}

function Docs(): React.ReactElement {
  return (
    <section className="flex flex-col gap-4" data-testid="docs-screen">
      <DocsHeader />
      <ErrorBoundary fallback={({ reset }) => <DocsError reset={reset} />}>
        <Suspense fallback={<DocsSkeleton />}>
          <DocsBody />
        </Suspense>
      </ErrorBoundary>
    </section>
  );
}

export const Route = createFileRoute("/_app/docs")({
  component: Docs,
  staticData: { title: "Documents" },
});
