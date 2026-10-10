import type { ParcelEvent } from "@parcel/core";
import { formatDateTime } from "../format";

/** Events oldest first; the last one is the latest. */
export function Timeline({ events, labelledBy }: { events: ParcelEvent[]; labelledBy: string }) {
  return (
    <ol className="timeline" aria-labelledby={labelledBy}>
      {events.map((event, index) => {
        const latest = index === events.length - 1;
        return (
          <li key={`${event.timestamp}-${index}`} className={latest ? "timeline__item is-latest" : "timeline__item"}>
            <p className="timeline__what">
              {event.description}
              {latest && <span className="tag">Latest</span>}
            </p>
            <p className="timeline__where">{event.location}</p>
            <time className="timeline__when" dateTime={event.timestamp}>
              {formatDateTime(event.timestamp)}
            </time>
          </li>
        );
      })}
    </ol>
  );
}
