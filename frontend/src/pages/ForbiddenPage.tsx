import { Link } from "react-router";

import { primaryLinkClass } from "../components/ui/Button";

export function ForbiddenPage() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-start py-16">
      <span className="rounded-full bg-signal-high-tint px-3 py-1 text-sm font-medium text-signal-high">Error 403</span>
      <h1 className="mt-5 text-3xl font-semibold tracking-tight text-ink sm:text-4xl">Authorised personnel only.</h1>
      <p className="mt-3 text-ink-soft">
        Your role does not include this part of SiteSense. If you need it for your work, ask your company admin to
        review your access.
      </p>
      <div aria-hidden="true" className="hazard-band mt-8 h-1.5 w-40 rounded-full" />
      <Link to="/" className={`mt-8 ${primaryLinkClass}`}>
        Back to your dashboard
      </Link>
    </div>
  );
}
