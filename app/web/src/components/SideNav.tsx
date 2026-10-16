import { useCallback, useEffect, useRef, useState } from "react";
import { BoxIcon, CloseIcon, MenuIcon } from "./Icons";
import { HOME_HREF, parseRoute, useHash } from "../router";

function getIsDesktop(): boolean {
  if (typeof window === "undefined" || typeof window.innerWidth === "undefined") {
    return true;
  }
  return window.innerWidth >= 1024;
}

export function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(getIsDesktop);

  useEffect(() => {
    function onResize() {
      setIsDesktop(getIsDesktop());
    }
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  return isDesktop;
}

function getCurrentSection(hash: string): "home" | "recent" | "status-guide" | null {
  const route = parseRoute(hash);
  if (route.name !== "home") return null;
  const raw = hash.replace(/^#/, "");
  const path = raw.split("?")[0] ?? "";
  if (path === "recent" || path === "/recent") return "recent";
  if (path === "status-guide" || path === "/status-guide") return "status-guide";
  return "home";
}

export function SideNav() {
  const [isOpen, setIsOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const isDesktop = useIsDesktop();
  const hash = useHash();
  const currentSection = getCurrentSection(hash);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    toggleRef.current?.focus();
  }, []);

  useEffect(() => {
    if (isDesktop && isOpen) {
      setIsOpen(false);
    }
  }, [isDesktop, isOpen]);

  useEffect(() => {
    if (!isOpen) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        handleClose();
      }
    }

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isOpen, handleClose]);

  const renderNavLinks = (inDialog = false) => (
    <ul className="nav-links">
      <li>
        <a
          href={HOME_HREF}
          aria-current={currentSection === "home" ? "page" : undefined}
          className={`nav-link ${currentSection === "home" ? "nav-link--current" : ""}`}
          onClick={inDialog ? handleClose : undefined}
        >
          Track a parcel
        </a>
      </li>
      <li>
        <a
          href="#recent"
          aria-current={currentSection === "recent" ? "page" : undefined}
          className={`nav-link ${currentSection === "recent" ? "nav-link--current" : ""}`}
          onClick={inDialog ? handleClose : undefined}
        >
          Recent parcels
        </a>
      </li>
      <li>
        <a
          href="#status-guide"
          aria-current={currentSection === "status-guide" ? "page" : undefined}
          className={`nav-link ${currentSection === "status-guide" ? "nav-link--current" : ""}`}
          onClick={inDialog ? handleClose : undefined}
        >
          Status guide
        </a>
      </li>
    </ul>
  );

  return (
    <>
      <nav
        data-testid="left-nav"
        aria-label="Main navigation"
        className="left-nav"
        hidden={!isDesktop}
        style={{ display: isDesktop ? undefined : "none" }}
      >
        <div className="left-nav__brand">
          <a className="brand" href={HOME_HREF}>
            <BoxIcon />
            <span>Parcel Tracker</span>
          </a>
        </div>
        {renderNavLinks(false)}
      </nav>

      <div
        className="site-header__mobile-brand"
        hidden={isDesktop}
        style={{ display: isDesktop ? "none" : undefined }}
      >
        <button
          ref={toggleRef}
          type="button"
          className="nav-toggle"
          data-testid="nav-toggle"
          aria-label="Open navigation"
          aria-expanded={isOpen}
          onClick={() => setIsOpen((prev) => !prev)}
        >
          <MenuIcon />
        </button>
        <a className="brand" href={HOME_HREF}>
          <BoxIcon />
          <span>Parcel Tracker</span>
        </a>
      </div>

      {isOpen && (
        <div
          role="dialog"
          aria-modal="true"
          aria-label="Main navigation"
          className="nav-dialog"
        >
          <button
            type="button"
            className="nav-dialog__backdrop"
            aria-label="Close navigation"
            tabIndex={-1}
            onClick={handleClose}
          />
          <div className="nav-dialog__panel">
            <div className="nav-dialog__header">
              <a className="brand" href={HOME_HREF} onClick={handleClose}>
                <BoxIcon />
                <span>Parcel Tracker</span>
              </a>
              <button
                type="button"
                className="nav-dialog__close"
                aria-label="Close navigation"
                onClick={handleClose}
              >
                <CloseIcon />
              </button>
            </div>
            {renderNavLinks(true)}
          </div>
        </div>
      )}
    </>
  );
}
