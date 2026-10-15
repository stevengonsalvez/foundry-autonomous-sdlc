export const RECENT_SEARCHES_KEY = "recent_searches";
export const MAX_RECENT_SEARCHES = 5;

export function getRecentSearches(): string[] {
  if (typeof window === "undefined" || !window.localStorage) {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(RECENT_SEARCHES_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (item): item is string => typeof item === "string" && item.trim().length > 0
    );
  } catch {
    return [];
  }
}

export function saveRecentSearch(trackingNumber: string): string[] {
  const trimmed = trackingNumber.trim();
  if (!trimmed) {
    return getRecentSearches();
  }
  const current = getRecentSearches();
  const updated = [
    trimmed,
    ...current.filter((item) => item !== trimmed),
  ].slice(0, MAX_RECENT_SEARCHES);

  if (typeof window !== "undefined" && window.localStorage) {
    try {
      window.localStorage.setItem(RECENT_SEARCHES_KEY, JSON.stringify(updated));
    } catch {
      // ignore quota / security errors
    }
  }
  return updated;
}

export function clearRecentSearches(): void {
  if (typeof window !== "undefined" && window.localStorage) {
    try {
      window.localStorage.removeItem(RECENT_SEARCHES_KEY);
    } catch {
      // ignore
    }
  }
}
