"use client";

import { useEffect, useState } from "react";
import { CircleCheck, CircleDashed, CircleX, LoaderCircle, RotateCw } from "lucide-react";
import { cn } from "@/lib/utils";
import type { Job, JobEvent, StepName, StepStatus } from "@/lib/ipo";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS: Record<StepName, { label: string; detail: string }> = {
  parse: { label: "Read the document", detail: "Sections, risk headings and financial tables" },
  index: { label: "Build the search index", detail: "Lets agents find passages; a few minutes for a new document" },
  risk: { label: "Agent 1 · Risk factors", detail: "Scores every risk factor" },
  financial: { label: "Agent 2 · Financial health", detail: "Ratios, scorecard and red flags" },
  legal: { label: "Agent 5 · Legal & approvals", detail: "Cases against the company and missing approvals" },
  business: { label: "Agent 3 · Business & promoters", detail: "What it does, who controls it" },
  offer: { label: "Agent 4 · Offer & use of proceeds", detail: "Fresh issue vs offer for sale, peers" },
  score: { label: "Score", detail: "The rubric, calculated in Python" },
  synthesis: { label: "Agent 7 · Write the report", detail: "Summary, bull and bear cases" },
};

const GROUPS: { title: string; steps: StepName[] }[] = [
  { title: "Reading the document", steps: ["parse", "index"] },
  { title: "Specialist agents, working side by side", steps: ["risk", "financial", "legal", "business", "offer"] },
  { title: "Verdict", steps: ["score", "synthesis"] },
];

function StatusIcon({ status }: { status: StepStatus }) {
  if (status === "running") return <LoaderCircle className="size-5 animate-spin text-foreground" />;
  if (status === "done") return <CircleCheck className="size-5 text-emerald-600" />;
  if (status === "failed") return <CircleX className="size-5 text-destructive" />;
  return <CircleDashed className="size-5 text-muted-foreground/60" />;
}

const clock = (seconds: number) =>
  `${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, "0")}`;

type JobProgressProps = {
  job: Job; // events: everything received so far
  onRetry: () => void;
  retrying: boolean;
};

export function JobProgress({ job, onRetry, retrying }: JobProgressProps) {
  // A ticking clock while the job runs
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (job.status === "done" || job.status === "failed") return;
    const timer = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, [job.status]);

  const latest: Partial<Record<string, JobEvent>> = {};
  for (const event of job.events) latest[event.agent] = event;
  const elapsed = (job.finished_at ?? now) - job.created_at;

  let status: string;
  if (job.status === "queued") {
    const others = job.queue_position === 1 ? "1 other analysis" : `${job.queue_position} other analyses`;
    status = job.queue_position > 0 ? `Waiting for ${others} to finish` : "Starting…";
  } else if (job.status === "running") {
    status = `Running for ${clock(elapsed)}`;
  } else if (job.status === "done") {
    status = `Finished in ${clock(elapsed)}`;
  } else {
    status = "Stopped";
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analysing {job.filename}</CardTitle>
        <CardDescription aria-live="polite">{status}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {job.status === "failed" && (
          <div className="flex flex-col items-start gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm">
            <p className="text-destructive">{job.error ?? "The analysis stopped."}</p>
            <p className="text-muted-foreground">
              Steps that finished are saved, so trying again only repeats the rest.
            </p>
            <Button variant="outline" size="sm" onClick={onRetry} disabled={retrying}>
              {retrying ? <LoaderCircle className="animate-spin" /> : <RotateCw />}
              Try again
            </Button>
          </div>
        )}

        {GROUPS.map((group) => (
          <section key={group.title} className="flex flex-col gap-2">
            <h3 className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{group.title}</h3>
            <ol className="flex flex-col gap-3">
              {group.steps.map((step) => {
                const stepStatus = job.steps[step];
                const message = latest[step]?.message;
                return (
                  <li key={step} className="flex gap-3">
                    <span className="pt-0.5">
                      <StatusIcon status={stepStatus} />
                    </span>
                    <div className="min-w-0">
                      <p className={cn("font-medium", stepStatus === "waiting" && "text-muted-foreground")}>
                        {STEPS[step].label}
                      </p>
                      <p className="text-sm text-muted-foreground">
                        {message && stepStatus !== "waiting" ? message : STEPS[step].detail}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ol>
          </section>
        ))}

        {job.events.length > 0 && (
          <details className="text-sm">
            <summary className="cursor-pointer text-muted-foreground hover:text-foreground">
              Activity log ({job.events.length})
            </summary>
            <ol className="mt-2 flex max-h-64 flex-col gap-1 overflow-y-auto rounded-md bg-muted/40 p-3 font-mono text-xs">
              {job.events.map((event, i) => (
                <li key={i}>
                  <span className="text-muted-foreground">{clock(event.at)}</span> [{event.agent}] {event.message}
                </li>
              ))}
            </ol>
          </details>
        )}
      </CardContent>
    </Card>
  );
}
