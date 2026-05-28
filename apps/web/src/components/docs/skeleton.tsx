import { Skeleton } from "@/components/ui/skeleton";

export function DocsSkeleton(): React.ReactElement {
  return (
    <div className="grid grid-cols-2 gap-3" data-testid="docs-skeleton">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-[140px] rounded-md" />
      ))}
    </div>
  );
}
