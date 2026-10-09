import { useIsFetching, useQueryClient } from "@tanstack/react-query";
import type { ReactNode } from "react";

import { ApiError } from "../../api/client";
import { useHealth, useReadiness } from "../../api/health";
import { Button } from "../../components/ui/Button";
import { DimensionHeading } from "../../components/ui/DimensionHeading";
import { Sheet } from "../../components/ui/Sheet";
import { StatusBadge, type Tone } from "../../components/ui/StatusBadge";

interface ReadingProps {
  sheetCode: string;
  title: string;
  tone: Tone;
  status: string;
  value: ReactNode;
  unit?: string;
  footnote: ReactNode;
}

function Reading({ sheetCode, title, tone, status, value, unit, footnote }: ReadingProps) {
  return (
    <Sheet as="article" sheetCode={sheetCode} className="flex flex-col p-5" aria-label={title}>
      <h3 className="font-wide pr-12 text-[0.7rem] font-bold tracking-[0.18em] text-ink-soft uppercase">{title}</h3>
      <p className="mt-6 flex items-baseline gap-1.5">
        <span className="tabular font-mono text-4xl leading-none font-medium tracking-tight">{value}</span>
        {unit ? <span className="font-mono text-sm text-ink-faint">{unit}</span> : null}
      </p>
      <div className="mt-5 flex items-center justify-between gap-3 border-t border-dashed border-rule pt-4">
        <StatusBadge tone={tone} label={status} pulse={tone === "ok"} />
        <span className="truncate font-mono text-[0.7rem] text-ink-faint">{footnote}</span>
      </div>
    </Sheet>
  );
}

function errorNote(error: unknown): string {
  if (error instanceof ApiError) return error.requestId ? `ref ${error.requestId.slice(0, 8)}` : error.code;
  return "unknown error";
}

export function SystemReadings() {
  const queryClient = useQueryClient();
  const health = useHealth();
  const readiness = useReadiness();
  const checking = useIsFetching({ queryKey: ["health"] }) > 0;

  const api: ReadingProps = health.isPending
    ? { sheetCode: "R-01", title: "API · liveness", tone: "idle", status: "Checking", value: "--", footnote: "contacting" }
    : health.isError
      ? {
          sheetCode: "R-01",
          title: "API · liveness",
          tone: "down",
          status: "Offline",
          value: "--",
          footnote: errorNote(health.error),
        }
      : {
          sheetCode: "R-01",
          title: "API · liveness",
          tone: "ok",
          status: "Online",
          value: health.data.latencyMs,
          unit: "ms",
          footnote: `api v${health.data.data.version}`,
        };

  const dbOk = readiness.data?.data.checks.database === "ok";
  const db: ReadingProps = readiness.isPending
    ? { sheetCode: "R-02", title: "Database · readiness", tone: "idle", status: "Checking", value: "--", footnote: "postgresql" }
    : readiness.isError || !dbOk
      ? {
          sheetCode: "R-02",
          title: "Database · readiness",
          tone: "down",
          status: "Unavailable",
          value: "--",
          footnote: readiness.isError ? errorNote(readiness.error) : "postgresql",
        }
      : {
          sheetCode: "R-02",
          title: "Database · readiness",
          tone: "ok",
          status: "Ready",
          value: readiness.data.latencyMs,
          unit: "ms",
          footnote: "postgresql",
        };

  const web: ReadingProps = {
    sheetCode: "R-03",
    title: "Web client",
    tone: "ok",
    status: "Loaded",
    value: `v${__APP_VERSION__}`,
    footnote: import.meta.env.MODE,
  };

  return (
    <section aria-labelledby="readings-heading">
      <DimensionHeading id="readings-heading" annotation="auto · 30 s">
        System readings
      </DimensionHeading>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Reading {...api} />
        <Reading {...db} />
        <Reading {...web} />
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-4">
        <Button
          variant="primary"
          disabled={checking}
          onClick={() => {
            void queryClient.invalidateQueries({ queryKey: ["health"] });
          }}
        >
          {checking ? "Checking…" : "Re-check now"}
        </Button>
        <p className="text-sm text-ink-soft" aria-live="polite">
          {health.isError
            ? "The API is not answering. Is the backend running? See the README quick start."
            : readiness.isSuccess && !dbOk
              ? "The API is up but cannot reach PostgreSQL."
              : "Live checks against /api/v1/health."}
        </p>
      </div>
    </section>
  );
}
