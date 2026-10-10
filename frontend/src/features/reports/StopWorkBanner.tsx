import { Link } from "react-router";

import { useCloseAction, useProjectActions } from "../../api/issues";
import { Alert } from "../../components/ui/Alert";
import { Button } from "../../components/ui/Button";

/** Open stop-work flags on the project (BR-11): shown until the project manager clears them. */
export function StopWorkBanner({ projectId }: { projectId: string }) {
  const actions = useProjectActions(projectId);
  const close = useCloseAction();
  const flags = (actions.data ?? []).filter((a) => a.kind === "stop_work");
  if (flags.length === 0) return null;
  return (
    <Alert tone="error" title={flags.length === 1 ? "Stop-work flagged" : `${String(flags.length)} stop-work flags`}>
      <ul className="space-y-2">
        {flags.map((flag) => (
          <li key={flag.id} className="flex flex-wrap items-center justify-between gap-2">
            <span>
              “{flag.summary}”{" "}
              <Link to={`/reports/${flag.report_id}`} className="font-medium underline">
                See the report
              </Link>
            </span>
            {flag.can_close ? (
              <Button
                variant="danger"
                disabled={close.isPending}
                onClick={() => {
                  close.mutate({ id: flag.id, resolution: "done" });
                }}
              >
                Clear stop-work
              </Button>
            ) : (
              <span className="text-xs">Only the project manager can clear it.</span>
            )}
          </li>
        ))}
      </ul>
    </Alert>
  );
}
