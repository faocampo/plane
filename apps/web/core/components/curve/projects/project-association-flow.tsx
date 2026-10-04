/**
 * Copyright (c) 2023-present Plane Software, Inc. and contributors
 * SPDX-License-Identifier: AGPL-3.0-only
 * See the LICENSE file for details.
 */
import { useEffect, useRef } from "react";
import { ArrowRight, Check, Link2, LockKeyhole, RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@plane/propel/button";
import { cn } from "@plane/utils";
import type { useCurveProjectAssociation } from "@/hooks/use-curve-project-association";
import { associationMessages } from "./project-association-model";

type Flow = ReturnType<typeof useCurveProjectAssociation>;
const control =
  "mt-2 h-11 w-full min-w-0 rounded-md border border-subtle bg-surface-1 px-3 text-13 text-primary focus:outline-2 focus:outline-offset-2 focus:outline-accent-primary disabled:cursor-not-allowed disabled:opacity-60";
const focus = "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent-primary";

export function ProjectAssociationFlow({ flow }: { flow: Flow }) {
  const title = useRef<HTMLHeadingElement>(null);
  const previousStep = useRef(flow.step);
  useEffect(() => {
    if (previousStep.current !== flow.step && ["review", "unknown", "confirmed"].includes(flow.step))
      title.current?.focus();
    if (previousStep.current !== flow.step && flow.step === "choose")
      document.getElementById("association-product")?.focus();
    previousStep.current = flow.step;
  }, [flow.step]);
  const choosing = flow.step === "choose" || flow.step === "checking";
  const message = flow.issue && associationMessages[flow.issue];
  const selectedVisible = !!flow.project && !!flow.product;
  const confirmed = flow.step === "confirmed" && !!flow.receipt && selectedVisible;
  const noProducts = flow.productsState === "ready" && flow.products.length === 0;
  const availability = flow.discovery?.availability;

  return (
    <section
      aria-labelledby="project-association-heading"
      className="my-6 overflow-hidden rounded-xl border border-subtle bg-layer-1"
    >
      <div className="flex flex-wrap items-start justify-between gap-4 border-b border-subtle px-5 py-5 sm:px-6">
        <div className="max-w-2xl">
          <h2
            id="project-association-heading"
            ref={title}
            tabIndex={-1}
            className={cn("text-20 font-semibold tracking-tight text-primary", focus)}
          >
            {confirmed
              ? "Project associated"
              : flow.step === "unknown"
                ? "Recover the association result"
                : "Connect work to a Product"}
          </h2>
          <p className="mt-2 text-13 leading-6 text-secondary">
            {confirmed
              ? "The server confirmed the relationship below."
              : "Give an existing project Product context. Then define future changes through explicit Initiatives."}
          </p>
        </div>
        <span className="inline-flex items-center gap-1.5 text-12 text-secondary">
          {confirmed ? (
            <Check className="size-4" aria-hidden="true" />
          ) : (
            <Link2 className="size-4" aria-hidden="true" />
          )}
          {confirmed ? "Confirmed" : "Project → Product → Initiatives"}
        </span>
      </div>
      <div className="grid gap-6 px-5 py-5 sm:px-6 xl:grid-cols-[minmax(0,1fr)_minmax(13rem,0.4fr)]">
        <div className="min-w-0">
          {message && (
            <div role="alert" className="mb-5 flex items-start gap-3 text-13 leading-6 text-primary">
              {flow.issue === "denied" ? (
                <LockKeyhole className="mt-1 size-4 shrink-0" aria-hidden="true" />
              ) : (
                <TriangleAlert className="mt-1 size-4 shrink-0" aria-hidden="true" />
              )}
              <div>
                <p className="font-semibold">{message.title}</p>
                <p className="text-secondary">{message.detail}</p>
              </div>
            </div>
          )}
          {!flow.validSession ? (
            <p role="status" className="text-13 leading-6 text-secondary">
              Sign in to a verified Curve workspace to read Product context.
            </p>
          ) : choosing ? (
            <>
              <div className="grid gap-5 sm:grid-cols-2">
                <label className="min-w-0 text-12 font-medium text-primary" htmlFor="association-project">
                  Source project
                  <select
                    id="association-project"
                    className={control}
                    value={flow.projectId}
                    onChange={(event) => flow.choose("projectId", event.target.value)}
                    disabled={flow.step === "checking" || flow.visibleProjects.length === 0}
                  >
                    <option value="">Choose a project</option>
                    {flow.visibleProjects.map((project) => (
                      <option key={project.id} value={project.id}>
                        {project.name} · {project.identifier}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="min-w-0 text-12 font-medium text-primary" htmlFor="association-product">
                  Existing Product
                  <select
                    id="association-product"
                    className={control}
                    value={flow.productId}
                    onChange={(event) => flow.choose("productId", event.target.value)}
                    disabled={flow.step === "checking" || flow.productsState !== "ready" || noProducts}
                  >
                    <option value="">Choose a Product</option>
                    {flow.products.map((product) => (
                      <option key={product.id} value={product.id}>
                        {product.name} · {product.key}
                      </option>
                    ))}
                  </select>
                </label>
              </div>
              {flow.productsState === "loading" && (
                <div role="status" className="mt-4">
                  <p className="text-12 text-secondary">Reading current Products…</p>
                  <div aria-hidden="true" className="mt-2 h-2 w-2/3 rounded bg-layer-2" />
                </div>
              )}
              {noProducts && (
                <p role="status" className="mt-4 text-13 leading-6 text-secondary">
                  No active Products are available. An existing active Product is required before you can associate
                  work.
                </p>
              )}
              {flow.visibleProjects.length === 0 && (
                <p className="mt-4 text-13 text-secondary">No currently readable source project is available.</p>
              )}
              <div className="mt-5 flex flex-wrap items-center gap-3">
                <Button
                  size="xl"
                  className={focus}
                  onClick={() => void flow.check()}
                  disabled={!selectedVisible || flow.step === "checking"}
                  appendIcon={<ArrowRight aria-hidden="true" />}
                >
                  {flow.step === "checking" ? "Checking relationship…" : "Review association"}
                </Button>
                {flow.step === "checking" ? (
                  <Button size="xl" variant="secondary" onClick={flow.back} className={focus}>
                    Cancel check
                  </Button>
                ) : (
                  <Button
                    size="xl"
                    variant="secondary"
                    onClick={flow.refreshProducts}
                    className={focus}
                    prependIcon={<RefreshCw aria-hidden="true" />}
                  >
                    Refresh Products
                  </Button>
                )}
              </div>
            </>
          ) : (
            <>
              {selectedVisible ? (
                <div className="grid min-w-0 gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-center">
                  <div className="min-w-0">
                    <p className="text-12 text-secondary">Project</p>
                    <p className="mt-1 text-18 font-semibold break-words text-primary">{flow.project!.name}</p>
                    <p className="font-mono mt-1 text-11 break-all text-tertiary">{flow.project!.identifier}</p>
                  </div>
                  <ArrowRight className="size-5 rotate-90 text-tertiary sm:rotate-0" aria-hidden="true" />
                  <div className="min-w-0">
                    <p className="text-12 text-secondary">Product</p>
                    <p className="mt-1 text-18 font-semibold break-words text-primary">{flow.product!.name}</p>
                    <p className="mt-1 text-12 text-secondary">{flow.product!.key}</p>
                  </div>
                </div>
              ) : (
                <p role="status" className="text-13 leading-6 text-secondary">
                  Current source access is being checked. Protected relationship details are hidden until the source is
                  readable again.
                </p>
              )}
              {flow.discovery && selectedVisible && (
                <p className="mt-5 text-12 leading-5 text-secondary">
                  Product version {flow.discovery.product_version} · Availability observed{" "}
                  <time dateTime={flow.discovery.observed_at}>
                    {flow.discovery.observed_at.replace("T", " ").replace("Z", " UTC")}
                  </time>
                </p>
              )}
              {flow.step === "review" && availability !== "AVAILABLE" && (
                <p role="status" className="mt-4 text-13 leading-6 text-primary">
                  {availability === "ASSOCIATED_WITH_SELECTED_PRODUCT"
                    ? "This project is already associated with the selected Product. No new command is needed."
                    : "This project is already associated elsewhere. Choose another project or Product; this flow cannot move an existing relationship."}
                </p>
              )}
              {confirmed && (
                <dl className="mt-5 space-y-2 border-t border-subtle pt-4 text-12">
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    <dt className="text-secondary">Association</dt>
                    <dd className="font-mono min-w-0 break-all text-primary">{flow.receipt!.data.id}</dd>
                  </div>
                  <div className="flex flex-wrap gap-x-3 gap-y-1">
                    <dt className="text-secondary">Effective from</dt>
                    <dd className="text-primary">
                      <time dateTime={flow.receipt!.data.effective_at}>{flow.receipt!.data.effective_at}</time>
                    </dd>
                  </div>
                </dl>
              )}
              <div className="mt-5 flex flex-wrap gap-3">
                {flow.step === "review" && availability === "AVAILABLE" && (
                  <Button size="xl" className={focus} onClick={() => void flow.send()} disabled={!selectedVisible}>
                    Associate project
                  </Button>
                )}
                {flow.step === "sending" && (
                  <>
                    <p role="status" className="self-center text-13 text-secondary">
                      Waiting for the server result…
                    </p>
                    <Button size="xl" variant="secondary" className={focus} onClick={flow.stopWaiting}>
                      Stop waiting
                    </Button>
                  </>
                )}
                {flow.step === "unknown" && (
                  <Button size="xl" className={focus} onClick={() => void flow.send()} disabled={!selectedVisible}>
                    Retry same request
                  </Button>
                )}
                {!flow.locked && (
                  <Button size="xl" variant="secondary" className={focus} onClick={flow.back}>
                    {confirmed ? "Associate another project" : "Back to choices"}
                  </Button>
                )}
              </div>
              {flow.locked && (
                <p className="mt-4 text-12 leading-5 text-secondary">
                  Stopping or leaving cannot undo a server command. Keep this page open to recover the same request.
                </p>
              )}
            </>
          )}
        </div>
        <aside
          className="border-t border-subtle pt-5 xl:border-t-0 xl:border-l xl:pt-0 xl:pl-6"
          aria-label="Association boundary"
        >
          <h3 className="text-13 font-semibold text-primary">A relationship, with clear boundaries</h3>
          <ul className="mt-3 space-y-3 text-12 leading-5 text-secondary">
            <li>Project work, members and dates stay in Plane.</li>
            <li>Tasks enter future Initiatives only through explicit scope selection.</li>
            <li>Association grants no approval and starts no agent execution.</li>
          </ul>
        </aside>
      </div>
    </section>
  );
}
