/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { observer } from "mobx-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Flag, Plus, RefreshCw, FileText, ListChecks, CircleCheck, Clock3 } from "lucide-react";
import { Button } from "@makeplane/propel/components/button";
import type { CurveItemMetadata } from "@plane/types";
import { useUser } from "@/hooks/store/user";
import { useCurveRoadmapProducts, useCurveRoadmapOverview } from "@/hooks/use-curve-roadmap-directory";
import { useCurveRoadmapChoices } from "@/hooks/use-curve-roadmap-choices";
import { useCurveRoadmapApprovals } from "@/hooks/use-curve-roadmap-approvals";
import type { RoadmapApprovals } from "@/hooks/use-curve-roadmap-approvals";
import { itemCreationRecovery } from "./item-creation-recovery";
import { RoadmapItemCreateController } from "./item-create-controller";
import "../initiatives/initiative-workspace.css";
import "./roadmap-workspace.css";

export function roadmapInitiativeHref(slug: string, id: string) {
  return `/${encodeURIComponent(slug)}/curve/initiatives?initiative=${encodeURIComponent(id)}`;
}
function nextStep(item: CurveItemMetadata, statuses?: RoadmapApprovals) {
  if (!statuses || statuses.includes("UNAVAILABLE") || item.initiative.state === "PAUSED") return "Open item";
  if (statuses[0] === "EMPTY") return "Add PRD";
  if (statuses[0] === "READY") return "Submit PRD";
  if (["CHANGES", "UPDATING"].includes(statuses[0])) return "Update PRD";
  if (statuses[0] === "REVIEW") return "Review PRD";
  if (statuses[0] === "APPROVED") {
    if (statuses[1] === "EMPTY") return "Add plan";
    if (statuses[1] === "READY") return "Submit plan";
    if (statuses[1] === "REVIEW") return "Review plan";
    if (["CHANGES", "UPDATING"].includes(statuses[1])) return "Update plan";
  }
  return "Open item";
}
function Notice({ title, children, onRetry }: { title: string; children: string; onRetry?: () => void }) {
  return (
    <div role="status" className="py-10">
      <h2 className="text-18 font-semibold">{title}</h2>
      <p className="mt-2 max-w-prose text-14 text-secondary">{children}</p>
      {onRetry && (
        <div className="mt-4">
          <Button label="Try again" variant="secondary" size="lg" stretch="auto" onClick={onRetry} />
        </div>
      )}
    </div>
  );
}
const approvalLabels = {
  LOADING: "Checking…",
  EMPTY: "Document needed",
  READY: "Ready for review",
  REVIEW: "Review waiting",
  UPDATING: "Update needed",
  CHANGES: "Changes requested",
  APPROVED: "Approved",
  UNAVAILABLE: "Status unavailable",
  LOCKED: "Waiting for Product",
};
function MilestoneItems({
  slug,
  items,
  approvals,
}: {
  slug: string;
  items: CurveItemMetadata[];
  approvals: Record<string, RoadmapApprovals>;
}) {
  return (
    <ul className="divide-y divide-subtle">
      {items.map((item) => (
        <li key={item.id} className="roadmap-item-row">
          <div className="min-w-0">
            <Link
              className="focus-visible:outline-accent-primary font-semibold text-primary underline-offset-4 hover:underline focus-visible:outline-2"
              href={roadmapInitiativeHref(slug, item.initiative.id)}
            >
              {item.initiative.title}
            </Link>
            <p className="mt-2 text-12 text-secondary">
              {item.status.replaceAll("_", " ").toLowerCase()} · Product → Technical
            </p>
          </div>
          <div className="roadmap-approval-pair">
            {(["Product (PRD)", "Technical (plan)"] as const).map((label, index) => {
              const status = approvals[item.id]?.[index] ?? "LOADING";
              const Icon =
                status === "APPROVED"
                  ? CircleCheck
                  : status === "REVIEW"
                    ? Clock3
                    : index === 0
                      ? FileText
                      : ListChecks;
              return (
                <div key={label} className="roadmap-approval" data-status={status}>
                  <Icon className="size-5 shrink-0" aria-hidden="true" />
                  <div>
                    <strong>{label}</strong>
                    <span>{approvalLabels[status]}</span>
                  </div>
                </div>
              );
            })}
          </div>
          <Link className="roadmap-next-action" href={roadmapInitiativeHref(slug, item.initiative.id)}>
            {nextStep(item, approvals[item.id])}
            <ArrowRight className="size-4" aria-hidden="true" />
          </Link>
        </li>
      ))}
    </ul>
  );
}
function ProductRoadmap({
  slug,
  workspaceId,
  actorId,
  productId,
  onPendingChange,
  directoryAvailable,
}: {
  slug: string;
  workspaceId: string;
  actorId?: string;
  productId: string;
  onPendingChange: (pending: boolean) => void;
  directoryAvailable: boolean;
}) {
  const router = useRouter();
  const [roadmapId, setRoadmapId] = useState("");
  const [milestoneId, setMilestoneId] = useState("");
  const [cursors, setCursors] = useState<{ roadmaps?: string; milestones?: string; features?: string }>({});
  const [creating, setCreating] = useState(false);
  const creationRegion = useRef<HTMLElement>(null);
  useEffect(() => {
    if (creating) {
      creationRegion.current?.focus();
      creationRegion.current?.scrollIntoView({ block: "start" });
    }
  }, [creating]);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    if (!roadmapId || !actorId) return;
    try {
      const retained = itemCreationRecovery(window.sessionStorage, {
        workspaceSlug: slug,
        actorId,
        productId,
        roadmapId,
      }).read();
      if (retained) setCreating(true);
    } catch {
      // A corrupt or inaccessible journal must surface recovery rather than
      // presenting a fresh creation whose predecessor may still be unresolved.
      setCreating(true);
    }
  }, [slug, actorId, productId, roadmapId]);

  const changePending = useCallback(
    (value: boolean) => {
      setPending(value);
      onPendingChange(value);
    },
    [onPendingChange]
  );
  const choices = useCurveRoadmapChoices(slug, actorId, { workspaceId, productId }, roadmapId || undefined, cursors);
  const overview = useCurveRoadmapOverview(slug, actorId, { productId, roadmapId });
  const available = directoryAvailable && choices.choices.status === "READY" ? choices.choices.data : null;
  const roadmap = available?.roadmaps.results.find((entry) => entry.id === roadmapId);
  const milestone = available?.milestones?.results.find((entry) => entry.id === milestoneId);
  useEffect(() => {
    if (!available || pending) return;
    if (!roadmap) {
      setRoadmapId(available.roadmaps.results[0]?.id ?? "");
      setMilestoneId("");
    } else if (!milestone) setMilestoneId(available.milestones?.results[0]?.id ?? "");
  }, [available, roadmap, milestone, pending]);
  const displayed =
    overview.read.status === "READY"
      ? overview.read.data.items.filter((item) => item.milestone_id === milestoneId)
      : [];
  const approvals = useCurveRoadmapApprovals(slug, workspaceId, productId, actorId, displayed);
  const checked = displayed.every((item) => approvals[item.id] && !approvals[item.id].includes("LOADING"));
  const unavailableCount = displayed.filter((item) => approvals[item.id]?.includes("UNAVAILABLE")).length;
  const attention = displayed.filter(
    (item) =>
      item.initiative.state === "PAUSED" ||
      approvals[item.id]?.some((status) => ["REVIEW", "CHANGES", "UPDATING"].includes(status))
  );
  const canCreate = overview.read.status === "READY" && overview.read.data.canCreate && !!milestone;
  const refresh = () => {
    choices.refresh();
    overview.refresh();
  };
  const nextPage = (kind: "roadmaps" | "milestones" | "features", cursor: string | null | undefined) => {
    if (pending) return;
    setCursors((current) => ({
      ...current,
      [kind]: cursor ?? undefined,
      ...(kind === "roadmaps" ? { milestones: undefined } : {}),
    }));
    if (kind === "roadmaps") {
      setCreating(false);
      setRoadmapId("");
      setMilestoneId("");
    }
    if (kind === "milestones") {
      setCreating(false);
      setMilestoneId("");
    }
  };
  return (
    <>
      <div className="roadmap-toolbar">
        <label className="roadmap-field">
          Roadmap
          <select
            disabled={!available || pending}
            value={roadmapId}
            onChange={(event) => {
              setRoadmapId(event.target.value);
              setMilestoneId("");
              setCursors((current) => ({ ...current, milestones: undefined }));
              setCreating(false);
            }}
          >
            <option value="">Choose a roadmap</option>
            {available?.roadmaps.results.map((row) => (
              <option key={row.id} value={row.id}>
                {row.name}
              </option>
            ))}
          </select>
        </label>
        <Button
          label="Refresh"
          icon={<RefreshCw className="size-4" aria-hidden="true" />}
          size="lg"
          variant="secondary"
          stretch="auto"
          onClick={refresh}
        />
        {cursors.roadmaps && (
          <Button
            label="First roadmaps"
            size="lg"
            variant="secondary"
            stretch="auto"
            disabled={pending}
            onClick={() => nextPage("roadmaps", undefined)}
          />
        )}
        {available?.roadmaps.next_cursor && (
          <Button
            label="More roadmaps"
            size="lg"
            variant="secondary"
            stretch="auto"
            disabled={pending}
            onClick={() => nextPage("roadmaps", available.roadmaps.next_cursor)}
          />
        )}
      </div>
      {choices.choices.status === "UNAVAILABLE" && (
        <Notice title="Roadmap unavailable" onRetry={refresh}>
          Your choices could not be verified. Try again to check current access.
        </Notice>
      )}
      {choices.choices.status === "LOADING" && (
        <p role="status" className="py-6 text-secondary">
          Loading roadmap…
        </p>
      )}
      {available && !available.roadmaps.results.length && (
        <Notice title="No roadmaps available">This Product has no available roadmap on this page.</Notice>
      )}
      {available && roadmap && (
        <div className="roadmap-focus-layout">
          <nav aria-label="Milestones" className="roadmap-milestones">
            <h2 className="text-14 font-semibold">Milestones</h2>
            <div className="mt-4 space-y-2">
              {available.milestones?.results.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  disabled={pending}
                  aria-current={row.id === milestoneId ? "true" : undefined}
                  className="roadmap-milestone"
                  onClick={() => {
                    setMilestoneId(row.id);
                    setCreating(false);
                  }}
                >
                  <Flag aria-hidden="true" className="size-4 shrink-0" />
                  <span>{row.name}</span>
                </button>
              ))}
            </div>
            {cursors.milestones && (
              <Button
                label="First milestones"
                size="lg"
                variant="secondary"
                stretch="auto"
                disabled={pending}
                onClick={() => nextPage("milestones", undefined)}
              />
            )}
            {available.milestones?.next_cursor && (
              <Button
                label="More milestones"
                variant="secondary"
                size="lg"
                stretch="auto"
                disabled={pending}
                onClick={() => nextPage("milestones", available.milestones?.next_cursor)}
              />
            )}
          </nav>
          <section className="min-w-0" aria-labelledby="milestone-heading">
            {!milestone ? (
              <Notice title="Choose a milestone">Select an available milestone to see its items.</Notice>
            ) : (
              <>
                <header className="roadmap-milestone-header">
                  <div>
                    <h2 id="milestone-heading" className="text-24 font-semibold">
                      {milestone.name}
                    </h2>
                    <p className="mt-2 text-14 text-secondary">
                      {milestone.target_end ? `Target ${milestone.target_end}` : "Target date not set"}
                    </p>
                  </div>
                  <Button
                    label="Create item"
                    icon={<Plus aria-hidden="true" className="size-4" />}
                    size="lg"
                    variant="primary"
                    stretch="auto"
                    disabled={!canCreate || pending || creating}
                    onClick={() => setCreating(true)}
                  />
                </header>
                {overview.read.status === "LOADING" && (
                  <p role="status" className="py-8 text-secondary">
                    Loading items…
                  </p>
                )}
                {overview.read.status === "UNAVAILABLE" && (
                  <Notice title="Items unavailable" onRetry={overview.refresh}>
                    The complete item list could not be verified. Refresh to check current access.
                  </Notice>
                )}
                {overview.read.status === "READY" && (
                  <>
                    <section className="roadmap-attention" aria-labelledby="attention-heading">
                      <h3 id="attention-heading" className="text-16 font-semibold">
                        Needs attention{" "}
                        <span className="ml-2 text-secondary">
                          {checked && !unavailableCount ? attention.length : "—"}
                        </span>
                      </h3>
                      {attention.length ? (
                        <MilestoneItems slug={slug} items={attention} approvals={approvals} />
                      ) : (
                        <p className="mt-2 text-14 text-secondary">
                          {!checked
                            ? "Checking document approvals…"
                            : unavailableCount
                              ? "Some approval statuses could not be verified. Open an item to refresh document access."
                              : "No items awaiting review, changes, or resumed work."}
                        </p>
                      )}
                    </section>
                    <section className="mt-8" aria-labelledby="milestone-items-heading">
                      <h3 id="milestone-items-heading" className="text-18 font-semibold">
                        All items <span className="ml-2 text-secondary">{displayed.length}</span>
                      </h3>
                      {displayed.length ? (
                        <MilestoneItems slug={slug} items={displayed} approvals={approvals} />
                      ) : (
                        <Notice title="Start this milestone">
                          Create an item, choose its Product and Technical reviewers, then add your PRD.
                        </Notice>
                      )}
                    </section>
                  </>
                )}
              </>
            )}
          </section>
        </div>
      )}
      {creating && (
        <section ref={creationRegion} tabIndex={-1} className="roadmap-create-region" aria-label="Create roadmap item">
          <RoadmapItemCreateController
            workspaceSlug={slug}
            actorId={actorId}
            scope={{ productId, roadmapId }}
            selectedMilestoneId={milestoneId}
            milestones={available?.milestones?.results ?? []}
            features={available?.features.results ?? []}
            reviewers={available?.reviewers ?? []}
            choicesAvailable={!!available && !!milestone}
            onPendingChange={changePending}
            guardNavigation
            onCreated={(result) =>
              router.push(roadmapInitiativeHref(slug, result.resource_ref.initiative_ref.resource_id))
            }
          />
          {cursors.features && (
            <Button
              label="First Features"
              size="lg"
              variant="secondary"
              stretch="auto"
              disabled={pending}
              onClick={() => nextPage("features", undefined)}
            />
          )}
          {available?.features.next_cursor && (
            <div className="mt-4">
              <Button
                label="More Features"
                size="lg"
                variant="secondary"
                stretch="auto"
                disabled={pending}
                onClick={() => nextPage("features", available.features.next_cursor)}
              />
            </div>
          )}
          <div className="mt-5">
            <Button
              label="Close creation"
              variant="secondary"
              size="lg"
              stretch="auto"
              disabled={pending}
              onClick={() => setCreating(false)}
            />
          </div>
        </section>
      )}
    </>
  );
}
export const RoadmapWorkspace = observer(function RoadmapWorkspace({
  workspaceSlug,
  workspaceId,
}: {
  workspaceSlug: string;
  workspaceId: string;
}) {
  const user = useUser();
  const actorId = user.isAuthenticated ? user.data?.id : undefined;
  return (
    <RoadmapDirectory
      key={JSON.stringify([workspaceSlug, workspaceId, actorId])}
      slug={workspaceSlug}
      workspaceId={workspaceId}
      actorId={actorId}
    />
  );
});
function RoadmapDirectory({ slug, workspaceId, actorId }: { slug: string; workspaceId: string; actorId?: string }) {
  const products = useCurveRoadmapProducts(slug, workspaceId, actorId);
  const [productId, setProductId] = useState("");
  const [locked, setLocked] = useState(false);
  const available = products.read.status === "READY" ? products.read.data : [];
  const selected = available.find((row) => row.id === productId);
  return (
    <main className="roadmap-workspace">
      <header className="mb-8">
        <h1 className="text-30 font-semibold">Roadmaps</h1>
        <p className="mt-2 text-14 text-secondary">
          Follow the milestone. Move each item through Product and Technical review.
        </p>
      </header>
      <label className="roadmap-field mb-6 max-w-sm">
        Product
        <select
          value={selected?.id ?? ""}
          disabled={products.read.status !== "READY" || locked}
          onChange={(event) => setProductId(event.target.value)}
        >
          <option value="">Choose a Product</option>
          {available.map((row) => (
            <option key={row.id} value={row.id}>
              {row.name}
            </option>
          ))}
        </select>
      </label>
      {products.read.status === "LOADING" && <p role="status">Loading Products…</p>}
      {products.read.status === "UNAVAILABLE" && (
        <Notice title="Products unavailable" onRetry={products.refresh}>
          Your Product access could not be verified.
        </Notice>
      )}
      {products.read.status === "READY" && !available.length && (
        <Notice title="No active Products">An active Product is required before roadmap items can be created.</Notice>
      )}
      {productId && (
        <div>
          <ProductRoadmap
            key={productId}
            slug={slug}
            workspaceId={workspaceId}
            actorId={actorId}
            productId={productId}
            onPendingChange={setLocked}
            directoryAvailable={!!selected}
          />
        </div>
      )}
    </main>
  );
}
