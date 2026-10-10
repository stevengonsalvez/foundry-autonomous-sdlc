import type { ReactNode } from "react";

export function Loading({ label, rows = 3 }: { label: string; rows?: number }) {
  return (
    <div role="status" className="loading">
      <span className="visually-hidden">{label}</span>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="skeleton" aria-hidden="true" />
      ))}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="notice notice--empty">
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}

interface ErrorNoticeProps {
  title: string;
  /** Heading level to fit the page outline, default 3. */
  level?: 2 | 3;
  children: ReactNode;
  onRetry?: () => void;
  action?: ReactNode;
}

export function ErrorNotice({ title, level = 3, children, onRetry, action }: ErrorNoticeProps) {
  const Heading = `h${level}` as const;
  return (
    <div role="alert" className="notice notice--error">
      <Heading>{title}</Heading>
      <p>{children}</p>
      {onRetry && (
        <button type="button" className="button button--secondary" onClick={onRetry}>
          Try again
        </button>
      )}
      {action}
    </div>
  );
}
