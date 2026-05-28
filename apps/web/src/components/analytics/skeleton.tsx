import { Skeleton } from "@/components/ui/skeleton";

export function AnalyticsSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4" data-testid="analytics-skeleton">
      <div className="grid grid-cols-3 gap-4">
        <Skeleton className="h-[140px] rounded-md" />
        <Skeleton className="h-[140px] rounded-md" />
        <Skeleton className="h-[140px] rounded-md" />
      </div>
      <div className="grid grid-cols-2 gap-4">
        <Skeleton className="h-[240px] rounded-md" />
        <Skeleton className="h-[240px] rounded-md" />
      </div>
      <Skeleton className="h-[200px] rounded-md" />
    </div>
  );
}
