import { useEffect, useRef, useState, type FormEvent } from "react";
import { ArrowRightIcon } from "./Icons";
import {
  clearRecentSearches,
  getRecentSearches,
  saveRecentSearch,
} from "../recent-searches";

export function SearchForm({
  onSearch,
  showRecentSearches = false,
}: {
  onSearch: (trackingNumber: string) => void;
  showRecentSearches?: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [empty, setEmpty] = useState(false);
  const [recentSearches, setRecentSearches] = useState<string[]>(() =>
    showRecentSearches ? getRecentSearches() : []
  );

  useEffect(() => {
    if (showRecentSearches) {
      setRecentSearches(getRecentSearches());
    }
  }, [showRecentSearches]);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = input.current?.value.trim() ?? "";
    if (!value) {
      setEmpty(true);
      input.current?.focus();
      return;
    }
    const updated = saveRecentSearch(value);
    if (showRecentSearches) {
      setRecentSearches(updated);
    }
    onSearch(value);
  }

  function handleChipClick(trackingNumber: string) {
    const updated = saveRecentSearch(trackingNumber);
    if (showRecentSearches) {
      setRecentSearches(updated);
    }
    onSearch(trackingNumber);
  }

  function handleClear() {
    clearRecentSearches();
    setRecentSearches([]);
  }

  return (
    <form role="search" className="search" onSubmit={submit} noValidate>
      <label htmlFor="tracking-number">Tracking number</label>
      <div className="search__row">
        <input
          ref={input}
          id="tracking-number"
          name="trackingNumber"
          type="text"
          autoComplete="off"
          spellCheck={false}
          placeholder="PK1000000001"
          aria-invalid={empty ? true : undefined}
          aria-describedby={empty ? "tracking-number-hint tracking-number-error" : "tracking-number-hint"}
          onChange={() => setEmpty(false)}
        />
        <button type="submit" className="button button--primary">
          Track
          <ArrowRightIcon />
        </button>
      </div>
      <p id="tracking-number-hint" className="hint">
        Tracking numbers start with PK followed by ten digits.
      </p>
      {empty && (
        <p id="tracking-number-error" className="field-error">
          Enter a tracking number
        </p>
      )}
      {showRecentSearches && recentSearches.length > 0 && (
        <div className="recent-searches">
          <div className="recent-searches__header">
            <span className="recent-searches__title">Recent searches</span>
            <button
              type="button"
              className="recent-searches__clear"
              onClick={handleClear}
            >
              Clear history
            </button>
          </div>
          <ul className="recent-searches__list" aria-label="Recent searches">
            {recentSearches.map((item) => (
              <li key={item}>
                <button
                  type="button"
                  className="recent-searches__chip"
                  onClick={() => handleChipClick(item)}
                >
                  {item}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </form>
  );
}
