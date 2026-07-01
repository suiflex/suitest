import { cn } from "@/lib/utils";

/**
 * Neutral loading skeleton. Uses an elevated neutral surface with a subtle
 * left-to-right shimmer — never the brand accent (green), which previously
 * made loading states read as "passed".
 */
function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="skeleton"
      className={cn(
        "relative overflow-hidden rounded-md bg-bg-elev-2",
        "after:absolute after:inset-0 after:-translate-x-full",
        "after:bg-gradient-to-r after:from-transparent after:via-fg-1/[0.06] after:to-transparent",
        "after:[animation:suitest-shimmer_1.6s_ease-in-out_infinite]",
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
