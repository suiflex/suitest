import { Skeleton } from "@/components/ui/skeleton";

export function InboxSkeleton(): React.ReactElement {
  return (
    <div className="flex flex-col gap-[14px]" data-testid="inbox-skeleton">
      {Array.from({ length: 4 }).map((_, i) => (
        <Skeleton key={i} className="h-[96px] rounded-md" />
      ))}
    </div>
  );
}
