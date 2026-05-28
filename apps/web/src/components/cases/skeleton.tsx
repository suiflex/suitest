import { Skeleton } from "@/components/ui/skeleton";

export function CasesSkeleton(): React.ReactElement {
  return (
    <div className="flex gap-4" data-testid="cases-skeleton">
      <div className="flex w-[280px] flex-col gap-2">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-7 rounded-md" />
        ))}
      </div>
      <div className="flex-1 space-y-3">
        <Skeleton className="h-10 rounded-md" />
        <Skeleton className="h-32 rounded-md" />
        <Skeleton className="h-48 rounded-md" />
      </div>
    </div>
  );
}
