import { ListSkeleton } from "@/components/shared/ListSkeleton";

export function DefectsSkeleton(): React.ReactElement {
  return (
    <ListSkeleton
      testId="defects-skeleton"
      count={3}
      className="flex flex-col gap-3.5"
      rowClassName="h-[180px] rounded-md"
    />
  );
}
