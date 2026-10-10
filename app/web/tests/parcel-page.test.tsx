import { render, screen } from "@testing-library/react";
import ParcelPage from "../src/pages/Parcel";

// simple render helper
function renderWithProviders(ui: React.ReactElement) {
  return render(ui);
}

describe("Parcel page", () => {
  it("renders parcel lookup form", () => {
    renderWithProviders(<ParcelPage />);

    expect(screen.getByLabelText(/tracking number/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /track/i })).toBeInTheDocument();
  });
});
