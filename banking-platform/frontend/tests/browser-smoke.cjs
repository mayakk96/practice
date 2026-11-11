/* Real-browser smoke test against a running sandbox. Synthetic records only. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { randomUUID } = require("node:crypto");
const { chromium, request } = require("playwright");

const baseURL = process.env.BROWSER_BASE_URL || "http://127.0.0.1:5173";
const local = {};
const envFile = path.resolve(__dirname, "../../.env");
if (fs.existsSync(envFile)) {
  for (const line of fs.readFileSync(envFile, "utf8").split(/\r?\n/)) {
    if (line && !line.startsWith("#") && line.includes("=")) {
      const at = line.indexOf("=");
      local[line.slice(0, at)] = line.slice(at + 1);
    }
  }
}
const username = process.env.BROWSER_USERNAME || local.APP_API_USERNAME;
const password = process.env.BROWSER_PASSWORD || local.APP_API_PASSWORD;
const headers = username && password
  ? { Authorization: `Basic ${Buffer.from(`${username}:${password}`).toString("base64")}` }
  : {};
const screenshots = process.env.BROWSER_SCREENSHOT_DIR;
const date = process.env.BROWSER_BUSINESS_DATE || "2026-11-08";

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE_PATH ? { executablePath: process.env.BROWSER_EXECUTABLE_PATH } : {}),
    args: process.env.BROWSER_NO_SANDBOX === "true" ? ["--no-sandbox"] : [],
  });
  const api = await request.newContext({ baseURL, extraHTTPHeaders: headers });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.setDefaultTimeout(15000);
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const tag = randomUUID().slice(0, 8);
  const reference = `DEMO-BROWSER-${tag}`;
  async function post(url, body) {
    const response = await api.post(url, { data: body });
    assert(response.ok(), `API setup failed: ${url} HTTP ${response.status()}`);
    return response.json();
  }
  async function status(value) {
    await page.locator(".drawer .detail-status .badge").filter({ hasText: new RegExp(`^${value}$`, "i") }).waitFor();
  }
  async function action(button, title, expectedStatus) {
    await page.locator(".drawer").getByRole("button", { name: button, exact: true }).click();
    const dialog = page.getByRole("dialog", { name: title, exact: true });
    await dialog.waitFor();
    if (await dialog.locator("textarea").count()) await dialog.locator("textarea").fill("Synthetic browser verification; operator-reviewed action.");
    await dialog.getByRole("button", { name: "Confirm action", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    if (expectedStatus) await status(expectedStatus);
  }
  async function closeDetails() {
    const close = page.getByRole("button", { name: "Close details", exact: true });
    if (await close.count()) await close.click();
  }
  try {
    const customer = await post("/api/customers", { externalReference: `DEMO-BROWSER-C-${tag}`, displayName: "Synthetic Browser Customer" });
    const account = await post("/api/accounts", { customerId: customer.id, accountReference: `DEMO-BROWSER-A-${tag}`, currency: "USD" });
    await page.goto(baseURL);
    await page.getByRole("heading", { name: "A clear view of every payment.", exact: true }).waitFor();
    await page.locator(".loading-line").waitFor({ state: "hidden" });
    const login = page.getByRole("dialog", { name: "Connect to your workspace", exact: true });
    if (await login.isVisible()) {
      assert(username && password, "Secured sandbox requires BROWSER_USERNAME and BROWSER_PASSWORD or generated ../.env");
      await login.getByLabel("Username", { exact: true }).fill(username);
      await login.getByLabel("Password", { exact: true }).fill(password);
      await login.getByRole("button", { name: "Connect workspace", exact: true }).click();
      await login.waitFor({ state: "hidden" });
      await page.locator(".loading-line").waitFor({ state: "hidden" });
    }
    assert.equal(await page.locator(".error-banner").count(), 0, "Dashboard API reads should succeed");
    assert.equal(await page.evaluate(() => localStorage.length + sessionStorage.length), 0, "Credentials must remain in memory");
    if (screenshots) {
      fs.mkdirSync(screenshots, { recursive: true });
      await page.screenshot({ path: path.join(screenshots, "dashboard-desktop.png"), fullPage: true });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "Mobile layout must not overflow the viewport");
    if (screenshots) await page.screenshot({ path: path.join(screenshots, "dashboard-mobile.png"), fullPage: true });
    for (const name of ["Transactions", "Settlement", "Reconciliation", "Exceptions", "Knowledge & AI", "Overview"]) {
      await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name, exact: true }).click();
      await page.locator(".loading-line").waitFor({ state: "hidden" });
      assert.equal(await page.locator(".error-banner").count(), 0, `Mobile ${name} reads should succeed`);
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole("button", { name: "New payment", exact: true }).click();
    const payment = page.getByRole("dialog", { name: "New payment instruction", exact: true });
    await payment.getByLabel("Source account").selectOption(account.id);
    await payment.getByLabel("Amount", { exact: true }).fill("134.56");
    await payment.getByLabel("Business date", { exact: true }).fill(date);
    await payment.getByLabel("External reference", { exact: true }).fill(reference);
    const submitted = page.waitForResponse((response) => response.url().endsWith("/api/transactions") && response.request().method() === "POST");
    await payment.getByRole("button", { name: "Submit payment instruction", exact: true }).click();
    const transaction = await (await submitted).json();
    await status("Received");
    await action("Authorize", "Authorize payment", "Authorized");
    await action("Capture", "Capture payment", "Captured");
    await page.locator(".journal").first().waitFor();
    assert.equal(await page.locator(".journal").count(), 1, "Capture should display its balanced journal");
    assert((await page.locator(".journal").innerText()).includes("$134.56"));
    await action("Confirm clearing", "Confirm clearing", "Cleared");
    await closeDetails();
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Settlement", exact: true }).click();
    await page.getByRole("button", { name: "Create batch", exact: true }).click();
    const batchDialog = page.getByRole("dialog", { name: "Create settlement batch", exact: true });
    await batchDialog.getByLabel("Business date", { exact: true }).fill(date);
    await batchDialog.getByRole("button", { name: "Create batch", exact: true }).click();
    await status("Open");
    await action("Ready batch", "Ready settlement", "Ready");
    await action("Submit batch", "Submit settlement", "Submitted");
    await action("Confirm batch", "Confirm settlement", "Confirmed");
    await closeDetails();
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Reconciliation", exact: true }).click();
    await page.getByRole("button", { name: "Import evidence", exact: true }).click();
    const evidence = page.getByRole("dialog", { name: "Import external evidence", exact: true });
    await evidence.getByLabel("Source reference", { exact: true }).fill(`DEMO-BROWSER-EVIDENCE-${tag}`);
    await evidence.getByLabel("External records (JSON array)", { exact: true }).fill(JSON.stringify([{ externalReference: reference, amountMinor: 8456, currency: "USD", status: "SETTLED", businessDate: date, receivedDate: date }]));
    await evidence.getByRole("button", { name: "Import evidence", exact: true }).click();
    await evidence.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "Run reconciliation", exact: true }).click();
    const run = page.getByRole("dialog", { name: "Run reconciliation", exact: true });
    await run.getByLabel("Business date", { exact: true }).fill(date);
    await run.getByRole("button", { name: "Run reconciliation", exact: true }).click();
    await page.locator(".drawer .mismatch").filter({ hasText: reference }).waitFor();
    await page.locator(".drawer .mismatch").filter({ hasText: reference }).getByText("Amount mismatch", { exact: true }).waitFor();
    await closeDetails();
    const exceptionResponse = await api.get("/api/exceptions?size=100");
    const exception = (await exceptionResponse.json()).items.find((item) => item.transactionId === transaction.id);
    assert(exception, "Material mismatch should create an operational exception");
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Exceptions", exact: true }).click();
    await page.locator(".loading-line").waitFor({ state: "hidden" });
    await page.locator(".exception-row").filter({ hasText: exception.id.slice(0, 8) }).click();
    await page.locator(".drawer").getByRole("button", { name: "Explain evidence", exact: true }).click();
    const assistant = page.getByRole("dialog", { name: "Read-only incident evidence", exact: true });
    await assistant.getByText("$50.00", { exact: false }).waitFor();
    assert(await assistant.locator(".citations details").count(), "Incident explanation should cite runbook evidence");
    await assistant.getByRole("button", { name: "Close dialog", exact: true }).click();
    await action("Investigate", "Start investigation", "Investigating");
    await action("Record resolution", "Resolve exception", "Resolved");
    const unchanged = await api.get(`/api/transactions/${transaction.id}`);
    assert.equal((await unchanged.json()).status, "SETTLED", "Exception disposition must not change financial state");
    await closeDetails();
    await page.getByRole("navigation", { name: "Main navigation" }).getByRole("button", { name: "Knowledge & AI", exact: true }).click();
    await page.getByRole("button", { name: "Search knowledge", exact: true }).click();
    await page.getByRole("heading", { name: "Retrieved guidance", exact: true }).waitFor();
    assert(await page.locator(".knowledge-answer .citations details").count(), "Knowledge answer should show evidence citations");
    assert.deepEqual(errors, [], "Browser must not raise JavaScript runtime errors");
    console.log("PASS: desktop/mobile navigation, memory-only login, payment creation, authorization, capture/journal, clearing, settlement, evidence import, reconciliation mismatch, read-only assistant, audited exception resolution, and cited knowledge retrieval.");
  } finally {
    await api.dispose();
    await browser.close();
  }
})().catch((error) => { console.error(password ? String(error.message).replaceAll(password, "[redacted]") : error.message); process.exit(1); });
