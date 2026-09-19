import { cn } from "@/lib/utils";
import { RATING_STYLES } from "@/lib/format";
import type { Rating } from "@/lib/ipo";

export function RatingBadge({ rating, className }: { rating: Rating; className?: string }) {
  return (
    <span className={cn("inline-flex items-center rounded-md px-2 py-0.5 text-sm font-medium", RATING_STYLES[rating], className)}>
      {rating}
    </span>
  );
}
