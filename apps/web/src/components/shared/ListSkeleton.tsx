import { Skeleton } from "@/components/ui/skeleton";

interface ListSkeletonProps {
  /** Number of placeholder rows. */
  count: number;
  /** Container layout classes (flex column / grid + gap). */
  className: string;
  /** Per-row skeleton classes (height + radius). */
  rowClassName: string;
  testId: string;
}

/**
 * Shared loading placeholder: `count` skeleton rows inside a styled container.
 * Per-screen skeletons (inbox/defects/docs) delegate here with their own
 * layout, row size, and test id so the rendered DOM stays screen-specific.
 */
export function ListSkeleton({
  count,
  className,
  rowClassName,
  testId,
}: ListSkeletonProps): React.ReactElement {
  return (
    <div className={className} data-testid={testId}>
      {Array.from({ length: count }).map((_, i) => (
        <Skeleton key={i} className={rowClassName} />
      ))}
    </div>
  );
}
