// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
import { useState } from "react";
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
  const ready = props.initiative.state === "PLANNING" && product === "APPROVED";
  const productUnknown = product === "LOADING" || product === "UNAVAILABLE";
  return (
    <DocumentReviewStages
      statuses={[product, ready ? technical : productUnknown ? product : "LOCKED"]}
      prd={<LocalPrdReviewPanel {...props} onStatus={setProduct} />}
      plan={
        ready ? (
          <LocalPlanReviewPanel {...props} onStatus={setTechnical} />
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
