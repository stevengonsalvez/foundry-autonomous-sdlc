import { useRef, useState, type FormEvent } from "react";
import { ArrowRightIcon } from "./Icons";

export function SearchForm({ onSearch }: { onSearch: (trackingNumber: string) => void }) {
  const input = useRef<HTMLInputElement>(null);
  const [empty, setEmpty] = useState(false);

  function submit(event: FormEvent) {
    event.preventDefault();
    const value = input.current?.value.trim() ?? "";
    if (!value) {
      setEmpty(true);
      input.current?.focus();
      return;
    }
    onSearch(value);
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
    </form>
  );
}
