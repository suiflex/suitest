import { Skeleton } from "@/components/ui/skeleton";

export function DefectsSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-3.5" data-testid="defects-skeleton">
      {Array.from({ length: 3 }).map((_, i) => (
        <Skeleton key={i} className="h-[180px] rounded-md" />
      ))}
    </div>
  );
}
