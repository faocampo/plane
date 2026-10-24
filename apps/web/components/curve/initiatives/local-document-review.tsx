// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useCallback, useState } from "react";
import type { ICurveInitiative } from "@plane/types";
import { DocumentReviewStages } from "./document-review-stages";
import type { DocumentApprovalStatus } from "./document-review-stages";
import { LocalPrdReviewPanel } from "./local-prd-review-panel";
import { LocalPlanReviewPanel } from "./local-plan-review-panel";
type Props = { workspaceSlug: string; initiative: ICurveInitiative; viewerId?: string; onReviewSaved: () => void };
export function LocalDocumentReview(props: Props) {
  return (
    <LocalDocumentReviewContent
      key={`${props.workspaceSlug}:${props.initiative.id}:${props.initiative.version}:${props.viewerId}`}
      {...props}
    />
  );
}
function LocalDocumentReviewContent(props: Props) {
  const [product, setProduct] = useState<DocumentApprovalStatus>("LOADING");
  const [technical, setTechnical] = useState<DocumentApprovalStatus>("LOADING");
  const [accessUnavailable, setAccessUnavailable] = useState(false);
  const onAccessFailure = useCallback((error: unknown) => {
    const status = (error as { status?: number } | null)?.status;
    if (status === 401 || status === 403 || status === 404) {
      setAccessUnavailable(true);
      setProduct("UNAVAILABLE");
      setTechnical("UNAVAILABLE");
    }
  }, []);
  const unavailable = (
    <section className="curve-prd-review">
      <h3>Document access unavailable</h3>
      <p>We couldn’t verify access to these documents. Refresh after your access is restored.</p>
      <button
        type="button"
        className="curve-prd-review__refresh"
        onClick={() => {
          setProduct("LOADING");
          setTechnical("LOADING");
          setAccessUnavailable(false);
        }}
      >
        Refresh document access
      </button>
    </section>
  );
  const ready = props.initiative.state === "PLANNING" && product === "APPROVED";
  const productUnknown = product === "LOADING" || product === "UNAVAILABLE";
  return (
    <DocumentReviewStages
      statuses={
        accessUnavailable
          ? ["UNAVAILABLE", "UNAVAILABLE"]
          : [product, ready ? technical : productUnknown ? product : "LOCKED"]
      }
      prd={
        accessUnavailable ? (
          unavailable
        ) : (
          <LocalPrdReviewPanel {...props} onStatus={setProduct} onAccessFailure={onAccessFailure} />
        )
      }
      plan={
        accessUnavailable ? (
          unavailable
        ) : ready ? (
          <LocalPlanReviewPanel {...props} onStatus={setTechnical} onAccessFailure={onAccessFailure} />
        ) : (
          <p>
            {product === "UNAVAILABLE"
              ? "Refresh Product requirements to check the current approval status."
              : product === "LOADING"
                ? "Checking Product approval…"
                : "Product approval comes first. The implementation plan is reviewed after the PRD."}
          </p>
        )
      }
    />
  );
}
