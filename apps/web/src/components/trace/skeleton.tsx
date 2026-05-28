import { Skeleton } from "@/components/ui/skeleton";

export function TraceSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4" data-testid="trace-skeleton">
      <Skeleton className="h-16 rounded-md" />
      <div className="grid grid-cols-3 gap-4">
        <Skeleton className="h-[420px] rounded-md" />
        <Skeleton className="h-[420px] rounded-md" />
        <Skeleton className="h-[420px] rounded-md" />
      </div>
    </div>
  );
}
