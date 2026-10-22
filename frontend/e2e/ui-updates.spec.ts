import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

const FIXTURES = path.resolve(process.cwd(), "../backend/fixtures");

async function register(page: Page) {
  const email = `ui-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Ravi Nair");
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill("Str0ngPassw0rd!");
  await page.getByLabel("Confirm password").fill("Str0ngPassw0rd!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
  return email;
}

test("notifications live behind the bell next to the logo", async ({ page }) => {
  await register(page);
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByRole("link", { name: "Notifications" })).toHaveCount(0);
  await nav.getByRole("button", { name: /^Notifications/ }).click();
  await expect(page.getByText("View all notifications")).toBeVisible();
  await page.getByRole("link", { name: "View all notifications" }).click();
  await expect(page.getByRole("heading", { name: "Notifications", exact: true })).toBeVisible();
});

test("Add transaction offers upload or manual entry; uploading opens the bill review", async ({ page }) => {
  await register(page);
  await page.getByRole("button", { name: "Add transaction" }).click();
  const chooser = page.getByRole("dialog");
  await expect(chooser.getByRole("button", { name: /Upload a bill/ })).toBeVisible();
  await expect(chooser.getByRole("button", { name: /Enter manually/ })).toBeVisible();
  await chooser.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "receipt-freshmart-grocery.pdf"));
  await expect(page).toHaveURL(/\/upload\?doc=/);
  const review = page.getByRole("dialog");
  await expect(review.getByRole("button", { name: /Confirm & save/ })).toBeVisible({ timeout: 30_000 });
  await expect(review.getByLabel("Total amount")).toHaveValue("595.00");
});

test("forgot password: a 6-digit code resets the password", async ({ page }) => {
  const email = await register(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await page.goto("/forgot-password");
  await page.getByLabel("Email").fill(email);
  await page.getByRole("button", { name: "Send code" }).click();
  // The dev server has no SMTP, so the page shows the code it would have emailed.
  const codeText = page.locator("span.font-mono");
  await expect(codeText).toHaveText(/^\d{6}$/);
  const code = (await codeText.textContent())!.trim();

  await page.getByLabel("6-digit code").fill(code === "000000" ? "111111" : "000000");
  await page.getByLabel("New password").fill("N3wPassw0rd!!");
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page.getByText(/That code is incorrect/)).toBeVisible();

  await page.getByLabel("6-digit code").fill(code);
  await page.getByRole("button", { name: "Update password" }).click();
  await expect(page).toHaveURL(/\/login/);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill("N3wPassw0rd!!");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
});

test("the bell is in the mobile header @mobile", async ({ page }) => {
  await register(page);
  await page.locator("header").getByRole("button", { name: /^Notifications/ }).click();
  await expect(page.getByText("View all notifications")).toBeVisible();
});

test("a new account gets its own workspace and the app never says household", async ({ page }) => {
  await register(page);
  await expect(page.getByRole("heading", { name: "Welcome to SmartSpend" })).toBeVisible();
  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav.getByText("Ravi's Workspace")).toBeVisible();
  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "Your workspaces" })).toBeVisible();
  await expect(page.getByText(/Only you can see this workspace/)).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/household/i);
});
