import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { FixtureCarrierClient, createParcelService } from "@parcel/core";
import { App } from "./App";
import { HttpParcelService } from "./http-parcel-service";
import "./styles.css";

// The static Pages build has no server, so it runs the same core service over the sample shipments in the browser.
const service =
  import.meta.env.MODE === "pages" ? createParcelService(new FixtureCarrierClient()) : new HttpParcelService();

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root element");

createRoot(root).render(
  <StrictMode>
    <App service={service} />
  </StrictMode>,
);
