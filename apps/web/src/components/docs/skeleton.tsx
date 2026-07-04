import { ListSkeleton } from "@/components/shared/ListSkeleton";

export function DocsSkeleton(): React.ReactElement {
  return (
    <ListSkeleton
      testId="docs-skeleton"
      count={4}
      className="grid grid-cols-2 gap-3"
      rowClassName="h-[140px] rounded-md"
    />
  );
}
