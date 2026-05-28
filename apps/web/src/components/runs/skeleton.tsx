import { Skeleton } from "@/components/ui/skeleton";

export function RunsSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-3" data-testid="runs-skeleton">
      <Skeleton className="h-[88px] rounded-md" />
      <div className="grid grid-cols-[260px_1fr] gap-4">
        <div className="flex flex-col gap-1.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-12 rounded-md" />
          ))}
        </div>
        <Skeleton className="h-[400px] rounded-md" />
      </div>
    </div>
  );
}
