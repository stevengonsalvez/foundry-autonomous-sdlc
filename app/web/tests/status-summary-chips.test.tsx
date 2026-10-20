import { describe, expect, it } from "vitest";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ParcelSummary } from "@parcel/core";
import { deferred, fakeService, renderApp } from "./helpers";

describe("status summary chips on home page", () => {
  it('renders a status summary chips container above the recent parcels table', async () => {
    // Use a deferred listParcels so we can observe the loading state before resolving
    const pending = deferred<ParcelSummary[]>();
    renderApp(fakeService({ listParcels: () => pending.promise }));

    // While pending the table isn't shown yet but we should show a loading status
    expect(screen.getByRole("status")).toHaveTextContent("Loading recent parcels");

    // Resolve the list and then the table and chips should appear
    pending.resolve([]);
    // If there are no parcels, the EmptyState will render instead of table, but the chips
    // feature should still render only when there are parcels. To be safe, render again
    // with the real fakeService dataset so chips and table appear.
    renderApp(fakeService());

    // The page renders and the recent parcels table is present
    await screen.findByRole("table", { name: "Recent parcels" });

    // The new feature should render a container with this test id
    expect(await screen.findByTestId("status-summary-chips")).toBeInTheDocument();
  });

  it("shows an 'All' chip with the total count and clicking a status chip filters the table and sets aria-pressed", async () => {
    renderApp(fakeService());

    // Wait for table and chips to appear
    const table = await screen.findByRole("table", { name: "Recent parcels" });
    const chips = await screen.findByTestId("status-summary-chips");

    // The All chip shows the total number of recent parcels (the baseline dataset has 8)
    const allChip = within(chips).getByRole("button", { name: /All/i });
    expect(allChip).toHaveTextContent(/All\s*\(/);
    expect(allChip).toHaveTextContent("8");

    // Find a concrete status label that exists in the sample data and click it
    const outForDeliveryChip = within(chips).getByRole("button", { name: /Out for delivery/i });
    await userEvent.click(outForDeliveryChip);

    // The clicked chip should be marked as pressed
    expect(outForDeliveryChip).toHaveAttribute("aria-pressed", "true");

    // The table should now only show parcels with the selected status
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(within(row).getByText(/Out for delivery/i)).toBeVisible();
    }
  });

  it("allows keyboard navigation between chips using arrow keys and Tab", async () => {
    renderApp(fakeService());

    // Ensure chips are rendered
    await screen.findByTestId("status-summary-chips");
    const chips = screen.getByTestId("status-summary-chips");
    const buttons = within(chips).getAllByRole("button");
    expect(buttons.length).toBeGreaterThan(1);

    // Focus the first chip
    buttons[0]!.focus();
    expect(buttons[0]).toHaveFocus();

    // ArrowRight should move focus to the next chip
    await userEvent.keyboard("{ArrowRight}");
    expect(buttons[1]).toHaveFocus();

    // ArrowLeft should move focus back
    await userEvent.keyboard("{ArrowLeft}");
    expect(buttons[0]).toHaveFocus();

    // Tab should move focus out of the chips container (to next focusable element)
    await userEvent.tab();
    // At least one of the buttons should no longer have focus
    const stillFocused = buttons.some((b) => b === document.activeElement);
    expect(stillFocused).toBe(false);
  });
});
