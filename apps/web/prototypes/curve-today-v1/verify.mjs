import assert from "node:assert/strict";
import { mkdir, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

const { default: puppeteer } = await import(process.env.CURVE_PUPPETEER_MODULE || "puppeteer");
const output = resolve(process.argv[2] || ".impeccable/review/curve-today-v1");
await mkdir(output, { recursive: true });
const browser = await puppeteer.launch({ headless: true });
const page = await browser.newPage();
const errors = [],
  network = [],
  checks = [];
page.on("pageerror", (error) => errors.push(String(error)));
page.on("request", (request) => {
  if (/^https?:/.test(request.url())) network.push(request.url());
});
const body = () => page.$eval("main", (element) => element.innerText);
const hasReview = () =>
  page.$$eval("main a", (elements) => elements.some((element) => element.textContent.includes("Review plan")));
const check = (name, condition) => {
  assert.ok(condition, name);
  checks.push(name);
};
const choose = async (state, role = "technical") => {
  await page.select("#principal", role);
  await page.select("#scenario", state);
};
try {
  await page.setViewport({ width: 1440, height: 1000 });
  await page.goto(new URL("./index.html", import.meta.url).href, { waitUntil: "load" });
  await page.evaluate(() => document.fonts.ready);
  check("current technical fixture has one decision", (await body()).includes("1 decision") && (await hasReview()));
  check(
    "all local brand images load",
    await page.$$eval("img", (imgs) => imgs.every((i) => i.complete && i.naturalWidth > 0))
  );
  await page.screenshot({ path: resolve(output, "desktop.png"), fullPage: true });
  await page.click('main a[href="#plan"]');
  await page.waitForFunction(() => document.querySelector("h1").textContent.includes("Associate"));
  await page.$$eval(".evidence details", (details) =>
    details.forEach((d) => {
      d.open = true;
    })
  );
  check(
    "destination exposes synthetic definition and evidence",
    (await body()).includes("DEMO-PLAN-01") && (await body()).includes("DEMO-EVIDENCE-01")
  );
  check("route change focuses destination heading", await page.evaluate(() => document.activeElement.tagName === "H1"));
  await page.screenshot({ path: resolve(output, "detail.png"), fullPage: true });
  await choose("revoked");
  check(
    "revocation clears open detail content",
    !(await body()).includes("Associate an existing project") && !(await body()).includes("DEMO-PLAN")
  );
  await page.click('main a[href="#today"]');
  await page.waitForFunction(() => document.querySelector("h1").textContent === "Today");
  check(
    "revocation clears queue content",
    !(await body()).includes("Associate an existing project") && !(await hasReview())
  );
  for (const state of ["loading", "failed", "stale"]) {
    await choose(state);
    check(
      `${state} is not zero and offers no decision action`,
      !(await body()).includes("0 decisions") && !(await hasReview())
    );
  }
  await choose("empty");
  check("confirmed empty has explicit zero", (await body()).includes("0 decisions") && !(await hasReview()));
  await choose("partial");
  check(
    "partial keeps the verified row but never reports a total",
    (await body()).includes("total is unknown") && !(await body()).includes("1 decision") && (await hasReview())
  );
  await choose("partial", "owner");
  check(
    "partial owner does not claim confirmed emptiness",
    (await body()).includes("No confirmed decisions") && !(await body()).includes("No decisions waiting")
  );
  for (const role of ["owner", "reviewer"]) {
    await choose("current", role);
    check(
      `${role} cannot get the technical decision from a label`,
      !(await hasReview()) && (await body()).includes("0 decisions")
    );
  }
  await choose("failed");
  await page.click("main [data-refresh]");
  check("refresh fixture recovers without a decision write", await hasReview());
  await page.setViewport({ width: 390, height: 844 });
  await page.screenshot({ path: resolve(output, "mobile.png"), fullPage: true });
  check(
    "mobile content does not overflow horizontally",
    await page.evaluate(() => document.documentElement.scrollWidth === innerWidth)
  );
  await page.click("#open-nav");
  check("mobile navigation is a modal dialog", await page.$eval("#navigation", (d) => d.open && d.matches(":modal")));
  for (let i = 0; i < 7; i++) {
    await page.keyboard.press("Tab");
    check(
      `drawer traps keyboard focus ${i + 1}`,
      await page.evaluate(() => document.activeElement.closest("dialog") !== null)
    );
  }
  await page.keyboard.press("Escape");
  check(
    "Escape restores navigation trigger focus",
    await page.evaluate(() => document.activeElement.id === "open-nav" && !document.querySelector("dialog").open)
  );
  await page.click("#open-nav");
  await page.mouse.click(380, 430);
  check("backdrop closes the drawer", await page.$eval("dialog", (d) => !d.open));
  await page.emulateMediaFeatures([{ name: "prefers-reduced-motion", value: "reduce" }]);
  await page.click("#open-nav");
  check(
    "reduced motion disables drawer animation",
    await page.$eval("dialog", (d) => getComputedStyle(d).animationName === "none")
  );
  await page.keyboard.press("Escape");
  check("no JavaScript errors", errors.length === 0);
  check("no network or API requests", network.length === 0);
  const result = {
    result: "PROTOTYPE_BROWSER_CHECKS_PASSED",
    checks,
    errors,
    network_requests: network.length,
    human_ux_acceptance: false,
    live_app_integration: false,
  };
  await writeFile(resolve(output, "browser-result.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(JSON.stringify({ result: result.result, checks: checks.length, output }));
} finally {
  await browser.close();
}
