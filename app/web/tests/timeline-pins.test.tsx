import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { fakeService, renderApp } from "./helpers";

describe("timeline location pins", () => {
  it("renders exactly 5 location pin svgs in the timeline", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");
    const timeline = await screen.findByRole("list", { name: "Shipment history" });

    // querySelectorAll on the timeline for visible svg icons with aria-hidden="true"
    const svgs = timeline.querySelectorAll('svg[aria-hidden="true"]');
    expect(svgs).toHaveLength(5);
  });

  it("each timeline__where begins with an svg[aria-hidden=\"true\"] and the first item still shows Rotterdam, NL", async () => {
    renderApp(fakeService(), "#/parcel/PK1000000001");
    const timeline = await screen.findByRole("list", { name: "Shipment history" });
    const items = within(timeline).getAllByRole("listitem");
    expect(items).toHaveLength(5);

    // First item must still contain the unchanged location text
    expect(items[0]).toHaveTextContent("Rotterdam, NL");

    // For every item, the .timeline__where element must start with an svg with aria-hidden="true"
    for (const item of items) {
      const where = item.querySelector(".timeline__where");
      // The acceptance criterion expects the svg to be the first child inside .timeline__where
      // so firstElementChild should be the svg element with aria-hidden="true".
      expect(where).not.toBeNull();
      const firstChild = where!.firstElementChild as Element | null;
      expect(firstChild).not.toBeNull();
      expect(firstChild?.tagName.toLowerCase()).toBe("svg");
      expect(firstChild?.getAttribute("aria-hidden")).toBe("true");

      // Also ensure the location text is still present inside the same .timeline__where element
      // (text content must include a location like "Rotterdam, NL" or other location strings)
      expect(where?.textContent).toBeTruthy();
    }
  });
});
