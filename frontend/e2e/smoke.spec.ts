import { expect, type Page, test } from "@playwright/test";

const SHOTS = process.env.E2E_SCREENSHOTS;

async function shot(page: Page, name: string) {
  if (SHOTS) await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

async function register(page: Page) {
  const email = `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Asha Menon");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Str0ngPassw0rd!");
  await page.getByLabel("Confirm password").fill("Str0ngPassw0rd!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  return email;
}

async function addTransaction(page: Page, opts: { amount: string; merchant: string; recordAs: "payment" | "bill"; ref?: string }) {
  await page.getByRole("button", { name: "Add transaction" }).first().click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Amount").fill(opts.amount);
  await dlg.getByLabel("Merchant / payee").fill(opts.merchant);
  await dlg.getByLabel("Record as").selectOption(opts.recordAs);
  if (opts.recordAs === "payment") await dlg.getByLabel("Payment method").selectOption("upi");
  await dlg.getByRole("button", { name: "Save transaction" }).click();
  await expect(dlg).toBeHidden();
}

test("receipt + UPI payment are reconciled and counted once; every page renders", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && !m.text().includes("401") && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(e.message));

  await register(page);
  await shot(page, "01-dashboard-empty");
  await page.goto("/transactions");
  await addTransaction(page, { amount: "450", merchant: "ABC Restaurant", recordAs: "bill" });
  await addTransaction(page, { amount: "450", merchant: "ABC RESTAURANT", recordAs: "payment" });
  await expect(page.getByText("ABC Restaurant").first()).toBeVisible();
  await shot(page, "02-transactions");

  await page.getByRole("link", { name: /Duplicates & Reconciliation/ }).click();
  await expect(page.getByText("Why these were matched")).toBeVisible();
  await expect(page.getByText("Amounts match exactly")).toBeVisible();
  await shot(page, "03-reconciliation");
  await page.getByRole("button", { name: "Link payment to bill" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/counted once/)).toBeVisible();

  await page.getByRole("link", { name: "Dashboard" }).click();
  const net = page.locator("text=Net spending").first().locator("..");
  await expect(net).toContainText("450.00");
  await expect(page.locator("text=Gross purchases").locator("..")).toContainText("450.00");
  await shot(page, "04-dashboard");

  for (const [path, heading] of [
    ["/upload", "Upload Bills"],
    ["/people", "People & Shared Expenses"],
    ["/budgets", "Budgets"],
    ["/recurring", "Recurring Expenses"],
    ["/accounts", "Accounts"],
    ["/analytics", "Analytics & Reports"],
    ["/categories", "Categories & Rules"],
    ["/notifications", "Notifications"],
    ["/settings", "Settings"],
  ]) {
    await page.goto(path);
    await expect(page.getByRole("heading", { name: heading, exact: true })).toBeVisible();
    await page.waitForLoadState("networkidle");
    await shot(page, `page-${path.slice(1)}`);
  }
  // dark theme renders
  await page.getByRole("button", { name: /Switch to dark theme/ }).click();
  await page.goto("/");
  await page.waitForLoadState("networkidle");
  await shot(page, "05-dashboard-dark");
  expect(errors, errors.join("\n")).toEqual([]);
});

test("mobile layout has navigation and no horizontal scroll @mobile", async ({ page }) => {
  await register(page);
  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(page.getByRole("link", { name: "Transactions" })).toBeVisible();
  await page.getByRole("link", { name: "Transactions" }).click();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  await shot(page, "06-mobile-transactions");
});
