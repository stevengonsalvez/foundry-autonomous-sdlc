import { render, screen } from "@testing-library/react";
import HomePage from "../src/pages/home";

// render helper
function renderWithProviders(ui: React.ReactElement) {
  return render(ui);
}

describe("Home page", () => {
  it("renders a level 1 heading and sets the document title", () => {
    renderWithProviders(<HomePage />);

    // The product copy was changed to "Track a parcel"
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(/Track a parcel/i);

    expect(document.title).toMatch(/Track a parcel/i);
  });
});
