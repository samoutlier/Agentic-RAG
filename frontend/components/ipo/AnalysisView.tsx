"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LoaderCircle, RotateCw } from "lucide-react";
import { toast } from "sonner";
import { ApiError } from "@/lib/api";
import { getAnalysis, getJob, rerunAnalysis, type Analysis, type Job, type JobEvent } from "@/lib/ipo";
import { Button } from "@/components/ui/button";
import { JobProgress } from "@/components/ipo/JobProgress";
import { Report } from "@/components/ipo/report/Report";

const POLL_MS = 2000;
const RETRY_MS = 5000; // after a failed poll, e.g. the backend restarting

type AnalysisViewProps = { documentId: string; jobId: string | null };

export function AnalysisView({ documentId, jobId }: AnalysisViewProps) {
  const router = useRouter();
  // The job being followed; null once there's none (finished, or never given)
  const [activeJobId, setActiveJobId] = useState(jobId);
  const [job, setJob] = useState<Job | null>(null);
  const [connectionLost, setConnectionLost] = useState(false);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [missing, setMissing] = useState<string | null>(null); // why there's no analysis to show
  const [retrying, setRetrying] = useState(false);

  // Follow the job: poll for progress until it finishes or fails
  useEffect(() => {
    if (!activeJobId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let after = 0; // events received so far: only newer ones are fetched
    let events: JobEvent[] = [];

    async function poll() {
      try {
        const next = await getJob(activeJobId!, after);
        if (cancelled) return;
        events = [...events, ...next.events];
        after = next.event_count;
        setJob({ ...next, events });
        setConnectionLost(false);
        if (next.status === "done") {
          // Show the report, and drop ?job= so a refresh opens it directly
          setActiveJobId(null);
          router.replace(`/analysis/${encodeURIComponent(documentId)}`);
        } else if (next.status !== "failed") {
          timer = setTimeout(poll, POLL_MS);
        }
      } catch (error) {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 404) {
          // Jobs live in the server's memory: after a restart, fall back
          // to whatever analysis is saved for this document
          setJob(null);
          setActiveJobId(null);
          return;
        }
        setConnectionLost(true);
        timer = setTimeout(poll, RETRY_MS);
      }
    }
    poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [activeJobId, documentId, router]);

  // With no job to follow, load the finished analysis
  useEffect(() => {
    if (activeJobId) return;
    let ignore = false;
    getAnalysis(documentId).then(
      (loaded) => {
        if (!ignore) setAnalysis(loaded);
      },
      (error) => {
        if (ignore) return;
        setMissing(
          error instanceof ApiError && error.status === 404
            ? "There's no finished analysis for this document. If it was still running, the server may have restarted."
            : error instanceof Error ? error.message : "Couldn't load the analysis.",
        );
      },
    );
    return () => {
      ignore = true;
    };
  }, [activeJobId, documentId]);

  async function handleRerun() {
    setRetrying(true);
    try {
      const started = await rerunAnalysis(documentId);
      setMissing(null);
      setJob(null);
      setActiveJobId(started.job_id);
      router.replace(`/analysis/${encodeURIComponent(documentId)}?job=${started.job_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Couldn't start the analysis again.");
    } finally {
      setRetrying(false);
    }
  }

  if (analysis && !activeJobId) return <Report analysis={analysis} />;

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-col gap-4">
      <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
        ← All analyses
      </Link>
      {connectionLost && (
        <p className="rounded-md bg-amber-50 px-3 py-2 text-sm text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Lost contact with the backend. Retrying…
        </p>
      )}
      {job ? (
        <JobProgress job={job} onRetry={handleRerun} retrying={retrying} />
      ) : missing ? (
        <div className="flex flex-col items-start gap-3 rounded-lg border p-6">
          <p>{missing}</p>
          <Button variant="outline" onClick={handleRerun} disabled={retrying}>
            {retrying ? <LoaderCircle className="animate-spin" /> : <RotateCw />}
            Analyse the saved document again
          </Button>
        </div>
      ) : (
        <p className="flex items-center gap-2 text-muted-foreground">
          <LoaderCircle className="size-4 animate-spin" /> Loading…
        </p>
      )}
    </div>
  );
}
