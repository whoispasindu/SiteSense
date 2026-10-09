import { isRouteErrorResponse, Link, useRouteError } from "react-router";

import { NotFoundPage } from "./NotFoundPage";

/** Shown when a route crashes. Never renders the error message or stack to the user. */
export function RouteErrorPage() {
  const error = useRouteError();

  if (isRouteErrorResponse(error) && error.status === 404) {
    return <NotFoundPage />;
  }

  if (import.meta.env.DEV) {
    console.error(error);
  }

  return (
    <div role="alert" className="mx-auto max-w-2xl px-6 py-24">
      <p className="font-mono text-xs tracking-[0.2em] text-ink-faint uppercase">Unexpected error</p>
      <h1 className="font-wide mt-4 text-4xl font-extrabold tracking-tight">Work stopped on this screen.</h1>
      <p className="mt-4 text-ink-soft">
        Something went wrong while showing this page. Your data has not been changed. Try again, and if it keeps
        happening, report it with the time it occurred.
      </p>
      <Link to="/" className="mt-8 inline-block font-semibold text-survey underline underline-offset-4">
        Return to the dashboard
      </Link>
    </div>
  );
}
