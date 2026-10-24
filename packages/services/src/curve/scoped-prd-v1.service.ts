/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkInitiativeScope,
  CurveExistingWorkMutation,
  CurveExistingWorkResult,
  CurveScopedPrdApproveV1,
  CurveScopedPrdCheckpointV1,
  CurveScopedPrdObservationV1,
  CurveScopedPrdObserveV1,
  CurveScopedPrdOperationAcceptance,
  CurveScopedPrdReturnV1,
  CurveScopedPrdScopeV1,
  CurveScopedPrdSubjectV1,
  CurveScopedPrdSubmitV1,
} from "@plane/types";
import {
  validateCurveScopedPrdApproveV1,
  validateCurveScopedPrdObserveV1,
  validateCurveScopedPrdReturnV1,
  validateCurveScopedPrdSubmitV1,
} from "./existing-work-contracts/validators.mjs";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkId,
  curveExistingWorkMutation,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import {
  decodeCurveScopedPrdAcceptance,
  decodeCurveScopedPrdObservationV1,
  decodeCurveScopedPrdSubjectV1,
  requireCurve,
  validateCurveScope,
  validateCurveWire,
} from "./existing-work-validation";

type ObservationExpectation = CurveScopedPrdScopeV1 &
  Partial<Pick<CurveScopedPrdObservationV1, "digest" | "initiative_version">>;
type SubjectExpectation = CurveScopedPrdScopeV1 &
  CurveScopedPrdCheckpointV1 &
  Partial<Pick<CurveScopedPrdSubjectV1, "digest" | "observation_set_id" | "observation_digest">>;
function root(workspaceSlug: string, scope: CurveExistingWorkInitiativeScope) {
  return `${curveExistingWorkRoot(workspaceSlug)}initiatives/${curveExistingWorkId(scope.initiativeId)}/scoped-prd/v1/`;
}
/** Explicit C2a edition. No legacy fallback, cached authority, command capability, or UI activation. */
export class CurveScopedPrdV1Service extends CurveExistingWorkTransport {
  captureObservation(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    payload: CurveScopedPrdObserveV1,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveScopedPrdObservationV1>> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const body = validateCurveWire(validateCurveScopedPrdObserveV1, payload, 65536);
      const command = curveExistingWorkMutation(options);
      const response = await this.mutate(
        `${root(workspaceSlug, identity)}observations/`,
        body,
        command,
        `"${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201);
        const { proposal_id, scope_revision_id, scope_revision, membership_digest } = body;
        const data = await decodeCurveScopedPrdObservationV1(response.data, identity, {
          proposal_id,
          scope_revision_id,
          scope_revision,
          membership_digest,
          initiative_version: command.expectedVersion,
        });
        this.checkCancellation(command.signal);
        return { data, etag: curveExistingWorkEtag(response, `"${command.expectedVersion}"`) };
      });
    });
  }
  retrieveObservation(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    observationId: string,
    expected: ObservationExpectation,
    signal?: AbortSignal
  ): Promise<CurveScopedPrdObservationV1> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const match = { ...expected, id: observationId };
      const response = await this.read(
        `${root(workspaceSlug, identity)}observations/${curveExistingWorkId(observationId)}/`,
        signal
      );
      return this.finishRead(decodeCurveScopedPrdObservationV1(response.data, identity, match), signal);
    });
  }
  retrieveCurrentSubject(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    expected: SubjectExpectation,
    signal?: AbortSignal
  ): Promise<CurveScopedPrdSubjectV1> {
    return this.retrieveSubjectAt(workspaceSlug, scope, expected, undefined, signal);
  }
  retrieveSubject(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    subjectId: string,
    expected: SubjectExpectation,
    signal?: AbortSignal
  ): Promise<CurveScopedPrdSubjectV1> {
    return this.retrieveSubjectAt(workspaceSlug, scope, expected, subjectId, signal);
  }
  private retrieveSubjectAt(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    expected: SubjectExpectation,
    subjectId?: string,
    signal?: AbortSignal
  ): Promise<CurveScopedPrdSubjectV1> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const match = { ...expected, ...(subjectId === undefined ? {} : { id: subjectId }) };
      const response = await this.read(
        `${root(workspaceSlug, identity)}subjects/${subjectId === undefined ? "current" : curveExistingWorkId(subjectId)}/`,
        signal
      );
      return this.finishRead(decodeCurveScopedPrdSubjectV1(response.data, identity, match), signal);
    });
  }
  submit(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    payload: CurveScopedPrdSubmitV1,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveScopedPrdOperationAcceptance>> {
    return this.command(workspaceSlug, scope, "submit", payload, options, validateCurveScopedPrdSubmitV1);
  }
  approve(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    payload: CurveScopedPrdApproveV1,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveScopedPrdOperationAcceptance>> {
    return this.command(workspaceSlug, scope, "approve", payload, options, validateCurveScopedPrdApproveV1);
  }
  returnForRevision(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    payload: CurveScopedPrdReturnV1,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveScopedPrdOperationAcceptance>> {
    return this.command(workspaceSlug, scope, "return-for-revision", payload, options, validateCurveScopedPrdReturnV1);
  }
  private command<T extends CurveScopedPrdSubmitV1 | CurveScopedPrdApproveV1 | CurveScopedPrdReturnV1>(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    route: "submit" | "approve" | "return-for-revision",
    payload: T,
    options: CurveExistingWorkMutation,
    validate: { (input: unknown): input is T; errors?: unknown }
  ): Promise<CurveExistingWorkResult<CurveScopedPrdOperationAcceptance>> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const body = validateCurveWire(validate, payload, 65536);
      const command = curveExistingWorkMutation(options);
      const response = await this.mutate(
        `${root(workspaceSlug, identity)}${route}/`,
        body,
        command,
        `"${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 202);
        const data = decodeCurveScopedPrdAcceptance(response.data, identity.workspaceId);
        requireCurve(response.headers.location === `${curveExistingWorkRoot(workspaceSlug)}operations/${data.id}/`);
        // Acceptance (including a replayed terminal Operation) is not an approval/body read or a fresh grant.
        this.checkCancellation(command.signal);
        return { data, etag: curveExistingWorkEtag(response, `"${command.expectedVersion}"`) };
      });
    });
  }
}
