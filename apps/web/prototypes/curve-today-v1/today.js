"use strict";
const main = document.querySelector("main");
const scenario = document.querySelector("#scenario");
const principal = document.querySelector("#principal");
const dialog = document.querySelector("#navigation");
const arrow = '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M4 12h16m-6-6 6 6-6 6"/></svg>';
const clock =
  '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7v5l3 2"/></svg>';
const alertIcon =
  '<svg aria-hidden="true" viewBox="0 0 24 24"><circle cx="12" cy="12" r="8"/><path d="M12 7v6m0 3h.01"/></svg>';
const roles = { technical: "Technical approver", owner: "Product owner", reviewer: "Code reviewer" };
document.querySelector("#mobile-navigation").append(document.querySelector(".navigation-content").cloneNode(true));
document.querySelector("#open-nav").addEventListener("click", () => dialog.showModal());
document.querySelector("#close-nav").addEventListener("click", () => dialog.close());
dialog.addEventListener("click", (event) => {
  if (event.target === dialog) dialog.close();
});
dialog.addEventListener("close", () => document.querySelector("#open-nav").focus());
dialog.addEventListener("keydown", (event) => {
  if (event.key !== "Tab") return;
  const stops = [...dialog.querySelectorAll("button:not(:disabled), a[href]")];
  const first = stops[0],
    last = stops[stops.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
});
dialog.querySelectorAll('a[href^="#"]').forEach((link) => link.addEventListener("click", () => dialog.close()));
window.matchMedia("(min-width:768px)").addEventListener("change", (event) => {
  if (event.matches && dialog.open) dialog.close();
});

function notice(message, danger = false) {
  return `<div class="notice ${danger ? "danger" : ""}">${alertIcon}<p>${message}</p></div>`;
}
function empty(title, body, retry = false) {
  return `<div class="empty"><h3>${title}</h3><p>${body}</p>${retry ? '<button class="button" data-refresh>Try again</button>' : ""}</div>`;
}
function row(stale = false) {
  return `<article class="row"><div class="status">${clock}Plan awaiting review</div>
    <h3>Associate an existing project</h3>
    <p class="description">Review the proposed task scope and rollback evidence before reserving work.</p>
    <div class="metadata"><span>Atlas product</span><span>Gate 2 · Technical plan</span><span>Revision 1 · Version 7</span></div>
    <div class="row-actions">${stale ? '<button class="button" disabled>Review unavailable</button>' : `<a class="button primary" href="#plan">Review plan ${arrow}</a>`}
      <span class="subtle">${stale ? "Refresh to check your access." : "Assigned to you for this Initiative."}</span></div>
  </article>`;
}
function queue() {
  switch (scenario.value) {
    case "loading":
      return '<div class="empty" aria-busy="true"><h3>Checking your decisions…</h3><p>Confirming current access and plan versions.</p><div class="skeleton" aria-hidden="true"></div><div class="skeleton short" aria-hidden="true"></div></div>';
    case "revoked":
      return empty(
        "Your workspace access changed",
        "This queue and its evidence are no longer available. Contact a workspace administrator if you still need access."
      );
    case "failed":
      return empty(
        "We couldn’t load your decisions",
        "Your pending work is unknown. Try again to check current access and evidence.",
        true
      );
    case "empty":
      return empty(
        "No decisions waiting for you",
        "Your accessible Initiatives were checked. Nothing currently needs your decision."
      );
    default:
      if (scenario.value === "partial")
        return (
          notice("Some Initiatives could not be checked. This is a partial queue; the total is unknown.") +
          (principal.value === "technical"
            ? row()
            : empty(
                "No confirmed decisions",
                "Other Initiatives could not be checked. Refresh to complete this queue."
              ))
        );
      if (scenario.value === "stale")
        return (
          notice(
            "This is an earlier snapshot. Refresh before opening a decision; access or the plan may have changed."
          ) +
          (principal.value === "technical"
            ? row(true)
            : empty("Current decisions unknown", "Refresh to check your assignments and access."))
        );
      if (principal.value !== "technical")
        return empty(
          "No decisions waiting for you",
          "This example's technical plan is assigned to another approver. Your role alone does not grant approval authority."
        );
      return row();
  }
}
function render(focus = false) {
  const isPlan = location.hash === "#plan";
  const name = roles[principal.value];
  const accessValid = !["loading", "revoked", "failed", "stale"].includes(scenario.value);
  const currentQueue = scenario.value === "current";
  const countLabel = currentQueue
    ? principal.value === "technical"
      ? "1 decision"
      : "0 decisions"
    : scenario.value === "empty"
      ? "0 decisions"
      : "Total unavailable";
  document.querySelector("#breadcrumb").textContent = isPlan ? "Product / Initiatives" : "Home / Today";
  document.querySelectorAll("nav a").forEach((a) => {
    if (a.getAttribute("href") === (isPlan ? "#plan" : "#today")) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (isPlan && accessValid) {
    main.innerHTML = `<a class="back-link" href="#today">Back to Today</a>
      <h1 tabindex="-1">Associate an existing project</h1>
      <p class="intro">Atlas product · Atlas workspace · Synthetic example</p>
      <div class="plan-summary"><span>Plan awaiting review</span><span>Revision 1 · Version 7</span><span>Gate 2 · Technical plan</span></div>
      <section class="evidence" aria-labelledby="plan-heading"><h2 id="plan-heading">Review the plan</h2>
        <p>${principal.value === "technical" ? "You are the assigned technical approver in this example. Read the definition and evidence before making a decision in the Initiative." : "You can read this example, but you are not its assigned technical approver."}</p>
        <details><summary>Read plan definition</summary><p>Outcome: associate a project already accessible in this workspace with one Initiative, preserving its existing task history.</p><ul><li>Use an existing project; do not create a duplicate.</li><li>Check current workspace access before association.</li><li>Keep execution manual after the decision.</li></ul><p class="subtle">Synthetic definition · Revision 1 · Example source DEMO-PLAN-01</p></details>
        <details><summary>Read decision evidence</summary><p>Example review: the selected project belongs to this workspace, the proposed tasks have been reviewed, and removing the association leaves the original project intact.</p><p class="subtle">Synthetic evidence for Revision 1 · Example source DEMO-EVIDENCE-01</p></details>
        <div class="detail-end"><p>This preview ends at evidence review. Recording a decision belongs to the live Initiative, where access and the plan version are checked again.</p><a class="button" href="#today">Return to Today</a></div>
      </section>`;
  } else if (isPlan) {
    main.innerHTML = `<a class="back-link" href="#today">Back to Today</a><h1 tabindex="-1">Decision unavailable</h1><p class="intro">Current access and evidence could not be confirmed. Return to Today and refresh before continuing.</p>`;
  } else {
    main.innerHTML = `<h1 tabindex="-1">Today</h1><p class="intro">Decisions that need your attention across Initiatives.</p>
      <div class="context-line"><span>Workspace <strong>Atlas</strong></span><span>Signed in as <strong>${name}</strong></span><span>View <strong>Assigned to me</strong></span></div>
      <div class="queue-layout"><section aria-labelledby="queue-heading"><div class="section-heading"><h2 id="queue-heading">Your decisions</h2><button class="text-button" data-refresh ${scenario.value === "loading" || scenario.value === "revoked" ? "disabled" : ""}>Refresh</button></div>
        <p class="subtle">${countLabel}${currentQueue || scenario.value === "empty" ? " · Checked just now in this example" : ""}</p>
        <div class="queue" role="status" aria-live="polite">${queue()}</div></section>
        <aside class="role-context" aria-label="Decision context"><h3>Start with the evidence</h3><p>Open the Initiative to read the current plan and the evidence behind its decision.</p><h3>Your assignment matters</h3><p>Only decisions available to the current principal belong here. Being a workspace owner does not make you a technical approver.</p><p class="quiet-rule">Tasks stay in My work. Updates and mentions stay in Inbox.</p></aside></div>`;
  }
  main.querySelectorAll("[data-refresh]").forEach((button) =>
    button.addEventListener("click", () => {
      scenario.value = "current";
      render(true);
    })
  );
  if (focus) main.querySelector("h1").focus();
}
function selectFixture() {
  render(false);
}
scenario.addEventListener("change", selectFixture);
principal.addEventListener("change", selectFixture);
window.addEventListener("hashchange", () => render(true));
render();
