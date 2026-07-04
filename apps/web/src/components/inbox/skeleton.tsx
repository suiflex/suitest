import { ListSkeleton } from "@/components/shared/ListSkeleton";

export function InboxSkeleton(): React.ReactElement {
  return (
    <ListSkeleton
      testId="inbox-skeleton"
      count={4}
      className="flex flex-col gap-[14px]"
      rowClassName="h-[96px] rounded-md"
    />
  );
}
