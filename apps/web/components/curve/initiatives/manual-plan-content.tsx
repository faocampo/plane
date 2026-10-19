// Copyright (c) 2023-present Plane Software, Inc. and contributors
// SPDX-License-Identifier: AGPL-3.0-only
// See the LICENSE file for details.
/* eslint-disable unicorn/no-array-sort -- Sort a fresh entries array for ES2022 compatibility. */
import type { ManualGate2Material } from "@plane/services";

type RecordValue = Record<string, unknown>;
const record = (value: unknown): value is RecordValue => !!value && typeof value === "object" && !Array.isArray(value);
export function materialBody(material: ManualGate2Material | null): RecordValue | null {
  if (!material) return null;
  try {
    const value: unknown = JSON.parse(material.content);
    return record(value) ? value : null;
  } catch {
    return null;
  }
}
const words = (value: string) => value.replaceAll("_", " ").toLowerCase();
const names: Record<string, string> = {
  in_scope: "Included work",
  out_of_scope: "Excluded work",
  verification_steps: "Acceptance checks",
  acceptance_ids: "Acceptance criteria",
  requirement_ids: "Requirements",
  rollback_plan: "Rollback and recovery",
  expected_components: "Affected components",
  proposed_delivery_refs: "Linked tasks",
  user_outcome: "Intended outcome",
  repository_binding_id: "Repository reference",
  predecessor_slice_key: "Depends on",
  successor_slice_key: "Dependent slice",
  base_commit: "Pinned base commit",
  command_text: "Manual check instruction",
  source_issue_id: "Task reference",
};
function fieldName(key: string) {
  return names[key] ?? words(key).replace(/^./, (c) => c.toUpperCase());
}

// Render every supplied field, including unknown additive fields, without interpreting instructions or HTML.
function ReadableValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-secondary">Not specified</span>;
  if (Array.isArray(value))
    return value.length ? (
      <ul className="list-disc space-y-3 pl-4">
        {value.map((item, index) => (
          <li key={index}>
            <ReadableValue value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span className="text-secondary">None listed</span>
    );
  if (record(value))
    return (
      <dl className="space-y-3">
        {Object.entries(value)
          .sort(([a], [b]) => {
            const order = [
              "user_outcome",
              "in_scope",
              "out_of_scope",
              "acceptance_ids",
              "verification_steps",
              "rollback_plan",
            ];
            const rank = (key: string) => (order.includes(key) ? order.indexOf(key) : order.length);
            return rank(a) - rank(b);
          })
          .map(([key, item]) => (
            <div key={key} className="min-w-0">
              <dt className="font-medium text-secondary">{fieldName(key)}</dt>
              <dd className="mt-1 [overflow-wrap:anywhere] break-words whitespace-pre-wrap">
                <ReadableValue value={item} />
              </dd>
            </div>
          ))}
      </dl>
    );
  return <span>{typeof value === "boolean" ? (value ? "Yes" : "No") : String(value)}</span>;
}

export function materialLabel(material: ManualGate2Material | null): string | null {
  const body = materialBody(material);
  if (!body) return null;
  if (typeof body.text === "string") return body.text.trim().slice(0, 100);
  if (Array.isArray(body.slices)) {
    const outcomes = body.slices
      .filter(record)
      .map((s) => s.user_outcome)
      .filter((s): s is string => typeof s === "string");
    if (outcomes.length) return outcomes.join("; ").slice(0, 100);
  }
  return null;
}

export function taskLabel(material: ManualGate2Material | null, installationId: string, issueId: string): string {
  const body = materialBody(material);
  const slices = Array.isArray(body?.slices) ? body.slices.filter(record) : [];
  const slice = slices.find(
    (s) =>
      Array.isArray(s.proposed_delivery_refs) &&
      s.proposed_delivery_refs.some(
        (ref) => record(ref) && ref.source_issue_id === issueId && ref.provider_installation_id === installationId
      )
  );
  return slice && typeof slice.user_outcome === "string"
    ? `${typeof slice.slice_key === "string" ? slice.slice_key + " · " : ""}${slice.user_outcome} · ${issueId}`
    : `Task title unavailable · ${issueId}`;
}

export function MaterialContent({ material }: { material: ManualGate2Material }) {
  const body = materialBody(material);
  if (!body)
    return (
      <p role="alert" className="mt-3 text-13 text-secondary">
        The protected material could not be displayed. Refresh and read it again.
      </p>
    );
  const slices = Array.isArray(body.slices) ? body.slices.filter(record) : [];
  const metadata = Object.fromEntries(
    Object.entries(body).filter(([key]) => !["slices", "repositories", "dependencies", "text"].includes(key))
  );
  return (
    <div className="mt-4 min-w-0 space-y-6 text-14 leading-6 [overflow-wrap:anywhere] text-primary">
      {material.kind === "RATIONALE" ? (
        <>
          <h4 className="font-semibold">Decision rationale</h4>
          <p className="max-w-prose whitespace-pre-wrap">
            {typeof body.text === "string" ? body.text : "Rationale text not provided."}
          </p>
        </>
      ) : (
        <>
          <section>
            <h4 className="mb-3 font-semibold">Work scope and acceptance</h4>
            {!slices.length && <p>No readable work slices were provided.</p>}
            {slices.map((slice, index) => (
              <section
                key={typeof slice.slice_key === "string" ? slice.slice_key : index}
                className="mt-5 border-t border-subtle pt-4"
              >
                <h5 className="mb-3 font-semibold">
                  {typeof slice.slice_key === "string" ? `Slice ${slice.slice_key}` : "Work slice"}
                </h5>
                <ReadableValue
                  value={Object.fromEntries(
                    Object.entries(slice).filter(
                      ([key]) =>
                        !key.endsWith("_ref") &&
                        ![
                          "owner",
                          "code_approver",
                          "repository_binding_id",
                          "proposed_delivery_refs",
                          "branch_name",
                        ].includes(key)
                    )
                  )}
                />
                <details className="mt-4">
                  <summary className="cursor-pointer py-2 font-medium focus-visible:outline-2">
                    Linked tasks, owners and policy references
                  </summary>
                  <ReadableValue
                    value={Object.fromEntries(
                      Object.entries(slice).filter(
                        ([key]) =>
                          key.endsWith("_ref") ||
                          [
                            "owner",
                            "code_approver",
                            "repository_binding_id",
                            "proposed_delivery_refs",
                            "branch_name",
                          ].includes(key)
                      )
                    )}
                  />
                </details>
                {!slice.in_scope && <p className="mt-2 text-secondary">Included work not specified.</p>}
                {!slice.out_of_scope && <p className="mt-2 text-secondary">Excluded work not specified.</p>}
                {!slice.verification_steps && <p className="mt-2 text-secondary">Acceptance checks not specified.</p>}
                {!slice.rollback_plan && <p className="mt-2 text-secondary">Rollback and recovery not specified.</p>}
              </section>
            ))}
          </section>
          <section>
            <h4 className="mb-3 font-semibold">Dependencies and ordering</h4>
            <ReadableValue value={body.dependencies} />
          </section>
        </>
      )}
      {material.kind === "DEFINITION" && (
        <details>
          <summary className="cursor-pointer py-2 font-medium focus-visible:outline-2">
            Repositories and pinned bases
          </summary>
          <ReadableValue value={body.repositories} />
        </details>
      )}
      <details>
        <summary className="cursor-pointer py-2 font-medium focus-visible:outline-2">
          Version and policy references
        </summary>
        <div className="mt-3">
          <ReadableValue value={metadata} />
        </div>
      </details>
      <details>
        <summary className="cursor-pointer py-2 font-medium focus-visible:outline-2">Technical source data</summary>
        <pre className="mt-3 max-h-80 overflow-auto rounded-md bg-layer-1 p-3 text-12 [overflow-wrap:anywhere] whitespace-pre-wrap">
          {material.content}
        </pre>
      </details>
    </div>
  );
}
