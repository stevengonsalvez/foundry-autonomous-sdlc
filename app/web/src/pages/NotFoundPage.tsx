import { HOME_HREF } from "../router";
import { useDocumentTitle } from "../useDocumentTitle";

export function NotFoundPage() {
  useDocumentTitle("Page not found");
  return (
    <section className="hero">
      <h1 tabIndex={-1}>Page not found</h1>
      <p className="lead">There is nothing at this address.</p>
      <a className="button button--primary" href={HOME_HREF}>
        Go to the home page
      </a>
    </section>
  );
}
