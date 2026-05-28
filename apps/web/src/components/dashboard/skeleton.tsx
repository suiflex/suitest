import { Skeleton } from "@/components/ui/skeleton";

/**
 * Dashboard loading skeleton — mirrors the four-row grid in the real view so
 * the layout doesn't jump when data arrives. Used as the `<Suspense>` fallback.
 */
export function DashboardSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4" data-testid="dashboard-skeleton">
      <div className="grid grid-cols-4 gap-[14px]">
        {Array.from({ length: 4 }).map((_, i) => (
          <Skeleton key={i} className="h-[88px] rounded-md" />
        ))}
      </div>
      <div className="grid grid-cols-2 gap-[18px]">
        <Skeleton className="h-[240px] rounded-md" />
        <Skeleton className="h-[240px] rounded-md" />
      </div>
      <div className="grid grid-cols-2 gap-[18px]">
        <Skeleton className="h-[240px] rounded-md" />
        <Skeleton className="h-[240px] rounded-md" />
      </div>
      <Skeleton className="h-[180px] rounded-md" />
    </div>
  );
}
