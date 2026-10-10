import { render, screen } from "@testing-library/react";
import Parcel from "../src/pages/Parcel";

describe("Parcel page", () => {
  it("renders parcel input and button", () => {
    render(<Parcel />);

    const input = screen.getByPlaceholderText(/Enter parcel id/i);
    const button = screen.getByRole("button");

    expect(input).toBeInTheDocument();
    expect(button).toBeInTheDocument();
  });
});
