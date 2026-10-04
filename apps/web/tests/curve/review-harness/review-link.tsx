/** Synthetic harness only: real native destinations are intentionally unavailable. */
import type { AnchorHTMLAttributes } from "react";
export default function ReviewLink({ children, className }: AnchorHTMLAttributes<HTMLAnchorElement>) {
  return (
    <button type="button" disabled className={className} title="Native destination unavailable in this isolated review">
      {children}
    </button>
  );
}
