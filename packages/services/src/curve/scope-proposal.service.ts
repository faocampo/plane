/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import type {
  CurveExistingWorkInitiativeScope,
  CurveExistingWorkMutation,
  CurveExistingWorkResult,
  CurveScopeProposalReplace,
  CurveScopeProposalRevision,
} from "@plane/types";
import { validateCurveScopeProposalReplace } from "./existing-work-contracts/validators.mjs";
import {
  CurveExistingWorkTransport,
  curveExistingWorkEtag,
  curveExistingWorkId,
  curveExistingWorkMutation,
  curveExistingWorkRoot,
} from "./existing-work-transport";
import {
  decodeCurveScopeProposal,
  requireCurve,
  requireCurveMatches,
  validateCurveScope,
  validateCurveWire,
} from "./existing-work-validation";

type RevisionExpectation = Partial<
  Pick<CurveScopeProposalRevision, "version" | "initiative_version" | "proposal_id" | "membership_digest">
>;
/** C1 finite DRAFT selection only; neither selection purpose establishes a binding. */
export class CurveScopeProposalService extends CurveExistingWorkTransport {
  retrieveCurrent(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    expected: RevisionExpectation = {},
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveScopeProposalRevision>> {
    return this.retrieve(workspaceSlug, scope, expected, undefined, signal);
  }
  retrieveRevision(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    revisionId: string,
    expected: RevisionExpectation = {},
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveScopeProposalRevision>> {
    return this.retrieve(workspaceSlug, scope, expected, revisionId, signal);
  }
  private retrieve(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    expected: RevisionExpectation,
    revisionId?: string,
    signal?: AbortSignal
  ): Promise<CurveExistingWorkResult<CurveScopeProposalRevision>> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const match = { ...expected, ...(revisionId === undefined ? {} : { id: revisionId }) };
      const root = `${curveExistingWorkRoot(workspaceSlug)}initiatives/${curveExistingWorkId(identity.initiativeId)}/scope-proposal/`;
      const response = await this.read(
        revisionId === undefined ? root : `${root}revisions/${curveExistingWorkId(revisionId)}/`,
        signal
      );
      const data = await this.finishRead(decodeCurveScopeProposal(response.data, identity, match), signal);
      // Historical revision ETags are not a fresh Initiative write precondition.
      return {
        data,
        etag: curveExistingWorkEtag(response, `"curve-initiative:${data.initiative_id}:v${data.initiative_version}"`),
      };
    });
  }
  replace(
    workspaceSlug: string,
    scope: CurveExistingWorkInitiativeScope,
    payload: CurveScopeProposalReplace,
    options: CurveExistingWorkMutation
  ): Promise<CurveExistingWorkResult<CurveScopeProposalRevision>> {
    return this.safely(async () => {
      const identity = validateCurveScope(scope);
      const body = validateCurveWire(validateCurveScopeProposalReplace, payload, 65536);
      const command = curveExistingWorkMutation(options);
      requireCurve(
        command.expectedVersion < Number.MAX_SAFE_INTEGER && body.expected_scope_revision < Number.MAX_SAFE_INTEGER
      );
      requireCurve(new Set(body.items.map((item) => item.source_issue_id)).size === body.items.length);
      const response = await this.mutate(
        `${curveExistingWorkRoot(workspaceSlug)}initiatives/${curveExistingWorkId(identity.initiativeId)}/scope-proposal/`,
        body,
        command,
        `"curve-initiative:${identity.initiativeId}:v${command.expectedVersion}"`
      );
      return this.verifyMutation(command.signal, async () => {
        requireCurve(response.status === 201);
        const data = await decodeCurveScopeProposal(response.data, identity, {
          version: body.expected_scope_revision + 1,
          initiative_version: command.expectedVersion + 1,
        });
        this.checkCancellation(command.signal);
        requireCurve(data.items.length === body.items.length);
        const byId = new Map(data.items.map((item) => [item.source_issue_id, item]));
        for (const item of body.items) {
          const returned = byId.get(item.source_issue_id);
          requireCurve(returned);
          requireCurveMatches(returned, item);
        }
        return {
          data,
          etag: curveExistingWorkEtag(response, `"curve-initiative:${data.initiative_id}:v${data.initiative_version}"`),
        };
      });
    });
  }
}
