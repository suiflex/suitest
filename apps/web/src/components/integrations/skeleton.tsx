import { Skeleton } from "@/components/ui/skeleton";

export function IntegrationsSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-4" data-testid="integrations-skeleton">
      <Skeleton className="h-8 w-[420px] rounded-md" />
      <div className="grid grid-cols-3 gap-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <Skeleton key={i} className="h-[140px] rounded-md" />
        ))}
      </div>
    </div>
  );
}
