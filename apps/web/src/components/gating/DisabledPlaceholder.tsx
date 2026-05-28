import { Lock } from "lucide-react";

interface DisabledPlaceholderProps {
  reason: string;
  cta?: { label: string; href: string };
}

/**
 * Visual fallback for `<Gated>` content. Renders a locked banner + reason +
 * optional CTA link.
 *
 * NOTE: M1b Task 3 uses a plain `<a href>` instead of TanStack Router's `Link`
 * because the route tree isn't fully wired yet (Task 4/5 wire navigation). Swap
 * to `<Link to={...}>` once router context is reliably available in callers
 * (and the unit-test ergonomics allow it).
 */
export function DisabledPlaceholder({ reason, cta }: DisabledPlaceholderProps): React.ReactElement {
  return (
    <div
      className="flex items-center gap-3 rounded-md border border-border bg-elev-1 p-4 text-fg-3"
      data-testid="disabled-placeholder"
    >
      <Lock className="h-4 w-4 text-fg-4" aria-hidden="true" />
      <div className="flex-1 text-[12.5px]">{reason}</div>
      {cta ? (
        <a href={cta.href} className="text-[12.5px] text-accent hover:underline">
          {cta.label}
        </a>
      ) : null}
    </div>
  );
}
