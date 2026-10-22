import path from "node:path";
import { expect, type Page, test } from "@playwright/test";

const FIXTURES = path.resolve(process.cwd(), "../backend/fixtures");
const SHOTS = process.env.E2E_SCREENSHOTS;
const shot = async (page: Page, name: string) => SHOTS && page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });

function watchErrors(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    // 4xx responses that the test deliberately provokes are surfaced as toasts, not bugs.
    if (m.type() === "error" && !/status of (401|409|422)/.test(m.text())) errors.push(m.text());
  });
  return errors;
}

async function register(page: Page) {
  await page.goto("/register");
  await page.getByLabel("Full name").fill("Bill Tester");
  await page.getByLabel("Email").fill(`bills-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`);
  await page.getByLabel("Password", { exact: true }).fill("Str0ngPassw0rd!");
  await page.getByLabel("Confirm password").fill("Str0ngPassw0rd!");
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard" })).toBeVisible();
}

async function addAccount(page: Page, name: string, type: string, extra: Record<string, string> = {}) {
  await page.goto("/accounts");
  await page.getByRole("button", { name: "Add account" }).click();
  const dlg = page.getByRole("dialog");
  await dlg.getByLabel("Name").fill(name);
  await dlg.getByLabel("Type").selectOption(type);
  for (const [lbl, v] of Object.entries(extra)) await dlg.getByLabel(lbl, { exact: true }).fill(v);
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toBeHidden();
}

test("uploaded bill: extract, review, correct, confirm, block re-upload, match the bank UPI row, count once", async ({ page }) => {
  const errors = watchErrors(page);
  await register(page);
  await addAccount(page, "XYZ Bank", "bank");

  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "receipt-freshmart-grocery.pdf"));
  const review = page.getByRole("dialog");
  await expect(review.getByRole("button", { name: /Confirm & save/ })).toBeVisible({ timeout: 30_000 });

  // Every extracted field the receipt actually contains.
  await expect(review.getByLabel("Merchant", { exact: true })).toHaveValue("FRESH MART SUPERMARKET");
  await expect(review.getByLabel("Date", { exact: true })).toHaveValue("2026-10-18");
  await expect(review.getByLabel("Time", { exact: true })).toHaveValue("19:42");
  await expect(review.getByLabel("Total amount")).toHaveValue("595.00");
  await expect(review.getByLabel("Invoice / receipt no.")).toHaveValue("FM-20481");
  await expect(review.getByLabel("UPI / transaction ref")).toHaveValue("429187654321");
  await expect(review.getByLabel("Discount")).toHaveValue("20.00");
  await expect(review.getByLabel("Tax (GST)")).toHaveValue("15.00");
  await expect(review.getByLabel("Payment method")).toHaveValue("upi");
  await expect(review.getByText("Line items (5)")).toBeVisible();
  await expect(review.getByLabel("name for line 1")).toHaveValue("Rice Ponni 5kg");
  await expect(review.getByLabel("line_total for line 5")).toHaveValue("130.00");
  await expect(review.getByLabel("Validation results").getByLabel("Error")).toHaveCount(0);
  // The suggested category is explained.
  await expect(review.getByText(/Auto: Groceries — found/)).toBeVisible();
  await shot(page, "bill-01-review");

  // Correct the merchant's display name, then confirm.
  await review.getByLabel("Merchant", { exact: true }).fill("Fresh Mart Supermarket");
  await review.getByRole("button", { name: /Confirm & save/ }).click();
  await expect(review).toBeHidden();
  // The list shows the corrected merchant name, not the raw extracted one.
  await expect(page.getByRole("row", { name: /receipt-freshmart-grocery\.pdf.*Fresh Mart Supermarket/ })).toBeVisible();
  await expect(page.getByRole("cell").getByText("Confirmed", { exact: true })).toBeVisible();

  // The same file again is blocked and reported.
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "receipt-freshmart-grocery.pdf"));
  await expect(page.getByText(/This exact file was already uploaded/)).toBeVisible();

  // Import the bank statement that contains the UPI payment for this bill.
  await page.getByRole("tab", { name: "Statements" }).click();
  await page.getByLabel("Account").selectOption({ label: "XYZ Bank" });
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "statement-bank-xyz.csv"));
  await expect(page.getByText(/5 new · 0 already imported/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/May match: Fresh Mart Supermarket/)).toBeVisible();
  await shot(page, "bill-02-statement-preview");
  await page.getByRole("button", { name: "Import 5 transaction(s)" }).click();
  await expect(page.getByText(/Imported 5 transaction/)).toBeVisible();

  // The bill and the UPI row are suggested with high confidence because they share the UPI reference.
  await page.goto("/reconciliation");
  const card = page.locator("div.rounded-lg", { hasText: "Exact transaction reference matched" }).first();
  await expect(card).toBeVisible();
  await expect(card.getByText(/High confidence/)).toBeVisible();
  await shot(page, "bill-03-match");
  await card.getByRole("button", { name: "Link payment to bill" }).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Confirm" }).click();
  await expect(page.getByText(/counted once/)).toBeVisible();
  await page.getByRole("tab", { name: /Duplicate uploads \(1\)/ }).click();
  await expect(page.getByText("receipt-freshmart-grocery.pdf").first()).toBeVisible();

  // 450 restaurant + 595 groceries (bill and UPI row counted once) + 300 to Rahul; the card bill payment is a transfer.
  await page.goto("/");
  await expect(page.locator("text=Gross purchases").locator("..")).toContainText("1,345.00");
  await expect(page.locator("text=Income").first().locator("..")).toContainText("85,000.00");
  expect(errors, errors.join("\n")).toEqual([]);
});

test("files that are not bills are rejected", async ({ page }) => {
  await register(page);
  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles({ name: "invoice.pdf", mimeType: "application/pdf", buffer: Buffer.from("MZ\x90\x00 this is an executable") });
  await expect(page.getByText(/Unsupported file type/)).toBeVisible();
  await expect(page.getByText("No documents yet")).toBeVisible();
});

test("photo of a bill: OCR fills the details, or manual entry when OCR is off; nothing is invented", async ({ page }) => {
  await register(page);
  await page.goto("/upload");
  await page.getByLabel("Type", { exact: true }).selectOption("upi_screenshot");
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "upi-screenshot-abc-restaurant.png"));
  const review = page.getByRole("dialog");
  await expect(review.getByRole("button", { name: /Confirm & save/ })).toBeVisible({ timeout: 30_000 });
  const ocrMissing = await review.getByText(/no OCR engine is installed/).isVisible();
  if (ocrMissing) {
    for (const lbl of ["Merchant", "Total amount"]) await expect(review.getByLabel(lbl, { exact: true })).toHaveValue("");
    await expect(review.getByRole("button", { name: /Confirm & save/ })).toBeDisabled();
    await review.getByLabel("Merchant", { exact: true }).fill("ABC Restaurant");
    await review.getByLabel("Date", { exact: true }).fill("2026-10-18");
    await review.getByLabel("Total amount").fill("450");
  } else {
    // Read from the screenshot by OCR.
    await expect(review.getByLabel("Merchant", { exact: true })).toHaveValue("ABC Restaurant");
    await expect(review.getByLabel("Date", { exact: true })).toHaveValue("2026-10-18");
    await expect(review.getByLabel("Total amount")).toHaveValue("450");
    await expect(review.getByLabel("UPI / transaction ref")).toHaveValue("429112345678");
  }
  await review.getByRole("button", { name: /Confirm & save/ }).click();
  await expect(review).toBeHidden();
  await page.goto("/transactions");
  await page.getByText("ABC Restaurant").first().click();
  await expect(page.getByRole("dialog").getByText("payment", { exact: true })).toBeVisible();
});

test("credit card bill: add card and bill, pay minimum then the rest, spending counted once", async ({ page }) => {
  const errors = watchErrors(page);
  await register(page);
  await addAccount(page, "SBI Savings", "bank", { "Opening balance": "50000" });

  await page.goto("/credit-cards");
  await expect(page.getByText("No credit cards yet")).toBeVisible();
  await page.getByRole("button", { name: "Add card" }).first().click();
  const dlg = page.getByRole("dialog");
  await expect(dlg.getByLabel("Type")).toHaveValue("credit_card");
  await dlg.getByLabel("Name").fill("HDFC Regalia");
  await dlg.getByLabel("Credit limit").fill("100000");
  await dlg.getByLabel("Statement day").fill("15");
  await dlg.getByLabel("Due day").fill("5");
  await dlg.getByLabel("Last 4 digits").fill("9912");
  await dlg.getByRole("button", { name: "Save" }).click();
  await expect(dlg).toBeHidden();
  await expect(page.getByText("HDFC Regalia")).toBeVisible();

  // A purchase on the card.
  await page.goto("/transactions");
  await page.getByRole("button", { name: "Add transaction" }).first().click();
  await page.getByRole("button", { name: /Enter manually/ }).click();
  const tx = page.getByRole("dialog");
  await tx.getByLabel("Amount").fill("3000");
  await tx.getByLabel("Merchant / payee").fill("Croma");
  await tx.getByLabel("Payment method").selectOption("credit_card");
  await tx.getByLabel("Account").selectOption({ label: "HDFC Regalia (INR)" });
  await tx.getByRole("button", { name: "Save transaction" }).click();
  await expect(tx).toBeHidden();

  // Add this month's bill, using the calculated total.
  await page.goto("/credit-cards");
  await expect(page.locator("text=Outstanding").locator("..")).toContainText("3,000.00");
  await page.getByRole("button", { name: "Add bill" }).click();
  const bill = page.getByRole("dialog");
  const now = new Date();
  const iso = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  await bill.getByLabel("Due date").fill(iso(new Date(now.getTime() + 10 * 86400000)));
  await bill.getByRole("button", { name: /Calculate from my card transactions/ }).click();
  await expect(bill.getByText(/purchases ₹3,000.00/)).toBeVisible();
  await bill.getByRole("button", { name: /Use ₹3,000.00 as total due/ }).click();
  await expect(bill.getByLabel("Total amount due")).toHaveValue("3000");
  await bill.getByLabel("Minimum amount due").fill("150");
  await bill.getByRole("button", { name: "Save bill" }).click();
  await expect(bill).toBeHidden();
  await expect(page.getByText(/Latest bill · ₹3,000.00/)).toBeVisible();
  await expect(page.getByText("Unpaid", { exact: true })).toBeVisible();
  await shot(page, "card-01-unpaid");

  // Pay the minimum.
  await page.getByRole("button", { name: "Pay", exact: true }).click();
  const pay = page.getByRole("dialog");
  await pay.getByRole("radio", { name: /Minimum/ }).click();
  await expect(pay.getByLabel("Amount", { exact: true })).toHaveValue("150");
  await expect(pay.getByLabel("Pay from").locator("option:checked")).toHaveText("SBI Savings"); // bank, not Cash
  await pay.getByRole("button", { name: "Record payment" }).click();
  await expect(pay).toBeHidden();
  await expect(page.getByText("Minimum paid", { exact: true })).toBeVisible();
  await expect(page.locator("text=Outstanding").locator("..")).toContainText("2,850.00");

  // Pay the rest.
  await page.getByRole("button", { name: "Pay", exact: true }).click();
  await expect(page.getByRole("dialog").getByLabel("Amount", { exact: true })).toHaveValue("2850");
  await page.getByRole("dialog").getByRole("button", { name: "Record payment" }).click();
  await expect(page.getByText("Paid", { exact: true })).toBeVisible();
  await expect(page.locator("text=Outstanding").locator("..")).toContainText("0.00");
  await page.getByRole("button", { name: "Details" }).click();
  await expect(page.getByRole("dialog").getByText("On time")).toHaveCount(2);
  await shot(page, "card-02-paid");
  await page.keyboard.press("Escape");

  // Spending is the purchase only; the two bill payments are transfers.
  await page.goto("/");
  await expect(page.locator("text=Gross purchases").locator("..")).toContainText("3,000.00");
  await expect(page.getByText(/HDFC Regalia.*bill/)).toHaveCount(0); // fully paid: no due banner
  await page.goto("/accounts");
  // 50,000 opening - 150 - 2,850 paid to the card
  await expect(page.locator("div.rounded-lg", { hasText: "SBI Savings" }).first()).toContainText("47,000.00");
  expect(errors, errors.join("\n")).toEqual([]);
});

test("water bill is recognised as Water, with the reason shown, and re-categorise leaves user choices alone", async ({ page }) => {
  await register(page);
  await page.goto("/upload");
  await page.locator('input[type="file"]').setInputFiles(path.join(FIXTURES, "bill-kwa-water.pdf"));
  const review = page.getByRole("dialog");
  await expect(review.getByRole("button", { name: /Confirm & save/ })).toBeVisible({ timeout: 30_000 });
  await expect(review.getByText(/Auto: Water — found .*water/)).toBeVisible();
  await shot(page, "bill-04-water-category");
  await review.getByRole("button", { name: /Confirm & save/ }).click();
  await expect(review).toBeHidden();
  await page.goto("/transactions");
  await page.getByText("KERALA WATER AUTHORITY").first().click();
  const detail = page.getByRole("dialog");
  await expect(detail.getByText("Water", { exact: true })).toBeVisible();
  await expect(detail.getByText(/Auto — found/)).toBeVisible();
  await page.keyboard.press("Escape");
  await page.goto("/categories");
  await page.getByRole("button", { name: /Re-apply automatic categorisation/ }).click();
  await expect(page.getByText(/Checked \d+ transactions|Updated \d+ of \d+/)).toBeVisible();
});
