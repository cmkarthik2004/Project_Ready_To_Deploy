// End-to-end browser test of the dashboard against a running FinRAG stack.
//   node e2e/smoke.mjs <base-url> <path-to-a-real-financial-document> ["question answerable from that document"]
// Registers a new user, checks genuine empty states, uploads the file through
// the Upload page, waits for real processing, and checks Library/Overview.
// With a question, also asks it on the Chat page (real LLM) and checks that the
// verified answer is displayed with its cited source (file name + location).
import assert from "node:assert/strict";
import { createRequire } from "node:module";

// Uses an installed Playwright (local devDependency or global via NODE_PATH).
const { chromium } = createRequire(import.meta.url)("playwright");

const base = process.argv[2] || "http://127.0.0.1:3000";
const file = process.argv[3];
const question = process.argv[4];
if (!file) { console.error("usage: node e2e/smoke.mjs <base-url> <file>"); process.exit(2); }

const browser = await chromium.launch();
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 } })).newPage();
const errors = [];
page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
page.on("pageerror", (e) => errors.push("uncaught: " + e.message));   // client-side crashes (error boundary)
const step = (s) => console.log("✓", s);

const email = `e2e-${Date.now()}@example.com`;
await page.goto(`${base}/register`);
await page.fill('input[type="email"]', email);
await page.fill('input[type="password"]', "Str0ngPassw0rd!");
await page.click('button:has-text("Create account")');
await page.waitForURL(`${base}/`);
step("registered and signed in");

await page.waitForSelector("text=No documents uploaded yet.");
step("overview shows the genuine empty state");
await page.goto(`${base}/analytics`);
await page.waitForSelector("text=No financial data available.");
step("analytics shows no data (nothing fabricated)");
await page.goto(`${base}/evaluation`);
await page.waitForSelector("text=No evaluation has been run yet.");
step("evaluation shows no results before a run");

await page.goto(`${base}/upload`);
await page.setInputFiles('input[type="file"]', file);
await page.click('button:has-text("Upload and process")');
await page.waitForSelector("text=accepted");
step("file accepted by the API");
await page.waitForSelector("text=view analysis", { timeout: 600_000 });
step("processing finished (status polled from the API)");

await page.goto(`${base}/documents`);
const row = page.locator("tbody tr").first();
assert.match(await row.innerText(), /processed/);
step("library lists the processed document");

await page.goto(`${base}/`);
await page.waitForSelector("text=Uploaded files");
const tiles = await page.locator(".num").allInnerTexts();
assert.equal(tiles[0].trim(), "1", "overview should count exactly one uploaded file");
step("overview counts come from the database (1 file)");

if (question) {
  await page.goto(`${base}/chat`);
  await page.fill('input[placeholder^="e.g."]', question);
  await page.click('button.btn-primary:has(svg)');
  await page.waitForSelector("text=Sources cited", { timeout: 600_000 });
  const cited = await page.locator("li:has-text('— page'), li:has-text('— sheet'), li:has-text('— row'), li:has-text('— table')").first().innerText();
  assert.ok(cited.includes(file.split("/").pop()), "citation should name the uploaded file: " + cited);
  step(`chat answer displayed with a verified citation (${cited.split("\n")[0]})`);
}

await page.goto(`${base}/settings`);
await page.waitForSelector("text=Processing limits");
step("settings loads");
assert.deepEqual(errors, [], "browser console errors: " + errors.join(" | "));
step("no browser console errors");
await browser.close();
console.log("E2E smoke test passed");
