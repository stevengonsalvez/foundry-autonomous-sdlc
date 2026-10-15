import { useEffect, useLayoutEffect, useRef, type MouseEvent } from "react";
import type { ParcelService } from "@parcel/core";
import { BoxIcon } from "./components/Icons";
import { ThemeToggle } from "./components/ThemeToggle";
import { HomePage } from "./pages/HomePage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { ParcelPage } from "./pages/ParcelPage";
import { HOME_HREF, parseRoute, useHash, type Route } from "./router";
import { ServiceContext } from "./service-context";

function routeKey(route: Route): string {
  return route.name === "parcel" ? `parcel:${route.trackingNumber}` : route.name;
}

export function App({ service }: { service: ParcelService }) {
  const route = parseRoute(useHash());
  const main = useRef<HTMLElement>(null);
  const key = routeKey(route);
  const shownKey = useRef(key);

  useLayoutEffect(() => {
    const container = main.current?.parentElement;
    if (container && container.parentElement === document.body) {
      let prev = container.previousElementSibling;
      while (prev) {
        const toRemove = prev;
        prev = prev.previousElementSibling;
        if (toRemove.querySelector("#main-content")) {
          toRemove.remove();
        }
      }
    }
  }, []);

  // Hash navigation keeps the same document, so hand focus to the new page's heading ourselves.
  useEffect(() => {
    if (shownKey.current === key) return;
    shownKey.current = key;
    main.current?.querySelector("h1")?.focus();
  }, [key]);

  function skipToContent(event: MouseEvent) {
    event.preventDefault();
    main.current?.focus();
  }

  return (
    <ServiceContext.Provider value={service}>
      <a className="skip-link" href="#main-content" onClick={skipToContent}>
        Skip to content
      </a>
      <header className="site-header">
        <div className="container">
          <a className="brand" href={HOME_HREF}>
            <BoxIcon />
            <span>Parcel Tracker</span>
          </a>
          <ThemeToggle />
        </div>
      </header>
      <main id="main-content" ref={main} tabIndex={-1} className="container">
        {route.name === "home" && <HomePage />}
        {route.name === "parcel" && <ParcelPage key={route.trackingNumber} trackingNumber={route.trackingNumber} />}
        {route.name === "unknown" && <NotFoundPage />}
      </main>
      <footer className="site-footer">
        <div className="container">Demo app with sample shipments. Not a real carrier.</div>
      </footer>
    </ServiceContext.Provider>
  );
}
