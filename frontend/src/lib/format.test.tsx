import { render, screen } from "@testing-library/react";
import { BarList } from "@/components/charts";
import { label, money, monthLabel, shiftMonth } from "@/lib/format";
import { categoryOptions, type Category } from "@/lib/queries";

describe("money", () => {
  it("formats decimal strings exactly, without float drift", () => {
    expect(money("0.30", "INR")).toBe("₹0.30");
    expect(money("123456.50", "INR")).toBe("₹1,23,456.50");
    // A value that is not representable as a binary float stays exact.
    expect(money("9007199254740993.10", "INR")).toBe("₹9,00,71,99,25,47,40,993.10");
  });
  it("shows a dash for missing values", () => {
    expect(money(null)).toBe("—");
    expect(money("")).toBe("—");
  });
});

describe("label", () => {
  it("humanises enum values and keeps acronyms", () => {
    expect(label("partially_paid")).toBe("Partially paid");
    expect(label("upi")).toBe("UPI");
    expect(label("upi_screenshot")).toBe("UPI screenshot");
    expect(label(null)).toBe("—");
  });
});

describe("months", () => {
  it("shifts across year boundaries", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(monthLabel("2026-10")).toMatch(/October 2026/);
  });
});

describe("categoryOptions", () => {
  const cat = (id: string, name: string, parent_id: string | null, kind = "expense", is_archived = false): Category => ({
    id,
    name,
    parent_id,
    kind,
    is_system: true,
    is_fixed: false,
    color: "",
    icon: "",
    is_archived,
  });
  it("nests children under parents and hides archived and other kinds", () => {
    const opts = categoryOptions(
      [cat("1", "Groceries", null), cat("2", "Dairy", "1"), cat("3", "Old", "1", "expense", true), cat("4", "Salary", null, "income"), cat("5", "Bills", null)],
      "expense",
    );
    expect(opts.map((o) => o.label.trim())).toEqual(["Bills", "Groceries", "Dairy"]);
  });
});

describe("BarList", () => {
  it("renders values as text so the chart is never colour-only", () => {
    render(<BarList currency="INR" items={[{ name: "Groceries", amount: "1200.00" }, { name: "Fuel", amount: "300.00" }]} />);
    expect(screen.getByText("Groceries")).toBeInTheDocument();
    expect(screen.getByText("₹1,200.00")).toBeInTheDocument();
  });
  it("has an empty state", () => {
    render(<BarList currency="INR" items={[]} />);
    expect(screen.getByText("No data for this period")).toBeInTheDocument();
  });
});
