import { useEffect, useRef, useState } from "react";
import { BoxIcon } from "./Icons";
import { HOME_HREF, parseRoute, useHash, type Route } from "../router";

export type NavSection = "track" | "recent" | "status-guide";

export function getActiveNavSection(hash: string, routeName: string): NavSection | null {
  if (routeName !== "home") return null;
  const clean = hash.replace(/^#\/?/, "");
  if (clean === "recent") return "recent";
  if (clean === "status-guide") return "status-guide";
  return "track";
}

interface NavItem {
  id: NavSection;
  label: string;
  href: string;
}

const NAV_ITEMS: readonly NavItem[] = [
  { id: "track", label: "Track a parcel", href: HOME_HREF },
  { id: "recent", label: "Recent parcels", href: "#recent" },
  { id: "status-guide", label: "Status guide", href: "#status-guide" },
];

function getIsDesktop(): boolean {
  if (typeof window === "undefined") return true;
  return window.innerWidth >= 1024;
}

function MenuIcon() {
  return (
    <svg
      width={20}
      height={20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <line x1="3" y1="12" x2="21" y2="12" />
      <line x1="3" y1="6" x2="21" y2="6" />
      <line x1="3" y1="18" x2="21" y2="18" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg
      width={20}
      height={20}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <line x1="18" y1="6" x2="6" y2="18" />
      <line x1="6" y1="6" x2="18" y2="18" />
    </svg>
  );
}

export function SideNav({
  currentRoute: propRoute,
  hash: propHash,
}: {
  currentRoute?: Route;
  hash?: string;
} = {}) {
  const storeHash = useHash();
  const hash = propHash ?? storeHash;
  const currentRoute = propRoute ?? parseRoute(hash);

  const [isDesktop, setIsDesktop] = useState(getIsDesktop);
  const [isOpen, setIsOpen] = useState(false);
  const toggleRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLDivElement>(null);

  const activeSection = getActiveNavSection(hash, currentRoute.name);

  useEffect(() => {
    function handleResize() {
      const desktop = window.innerWidth >= 1024;
      setIsDesktop(desktop);
      if (desktop) {
        setIsOpen(false);
      }
    }
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        setIsOpen(false);
        toggleRef.current?.focus();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen]);

  function closeAndFocusToggle() {
    setIsOpen(false);
    toggleRef.current?.focus();
  }

  return (
    <>
      <header className="site-header top-bar">
        <div className="container top-bar__inner">
          <a className="brand" href={HOME_HREF}>
            <BoxIcon />
            <span>Parcel Tracker</span>
          </a>
          <button
            type="button"
            className="nav-toggle"
            data-testid="nav-toggle"
            aria-label="Open navigation"
            aria-expanded={isOpen}
            ref={toggleRef}
            onClick={() => setIsOpen((prev) => !prev)}
            style={{ display: isDesktop ? "none" : undefined }}
          >
            <MenuIcon />
          </button>
        </div>
      </header>

      <nav
        data-testid="left-nav"
        aria-label="Main navigation"
        className="left-nav"
        style={{ display: isDesktop ? undefined : "none" }}
      >
        <div className="left-nav__brand">
          <a className="brand" href={HOME_HREF}>
            <BoxIcon />
            <span>Parcel Tracker</span>
          </a>
        </div>
        <ul className="nav-list">
          {NAV_ITEMS.map((item) => (
            <li key={item.id} className="nav-list__item">
              <a
                href={item.href}
                className="nav-link"
                aria-current={activeSection === item.id ? "page" : undefined}
              >
                {item.label}
              </a>
            </li>
          ))}
        </ul>
      </nav>

      {isOpen && (
        <>
          <button
            type="button"
            className="mobile-nav-backdrop"
            aria-label="Close navigation"
            tabIndex={-1}
            onClick={closeAndFocusToggle}
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Navigation"
            className="mobile-nav-dialog"
            ref={dialogRef}
            tabIndex={-1}
          >
            <div className="mobile-nav-dialog__header">
              <a className="brand" href={HOME_HREF} onClick={() => setIsOpen(false)}>
                <BoxIcon />
                <span>Parcel Tracker</span>
              </a>
              <button
                type="button"
                className="nav-close"
                aria-label="Close navigation"
                onClick={closeAndFocusToggle}
              >
                <CloseIcon />
              </button>
            </div>
            <ul className="nav-list nav-list--mobile">
              {NAV_ITEMS.map((item) => (
                <li key={item.id} className="nav-list__item">
                  <a
                    href={item.href}
                    className="nav-link"
                    aria-current={activeSection === item.id ? "page" : undefined}
                    onClick={() => setIsOpen(false)}
                  >
                    {item.label}
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </>
      )}
    </>
  );
}
