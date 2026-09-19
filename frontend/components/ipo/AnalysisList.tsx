"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { FileText, LoaderCircle, Trash } from "lucide-react";
import { toast } from "sonner";
import { deleteAnalysis, listAnalyses, type AnalysisSummary } from "@/lib/ipo";
import { formatDate } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { RatingBadge } from "@/components/ipo/RatingBadge";

export function AnalysisList() {
  const [analyses, setAnalyses] = useState<AnalysisSummary[] | null>(null); // null while loading
  const [loadError, setLoadError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let ignore = false; // a newer reload makes this result stale
    listAnalyses().then(
      (list) => {
        if (ignore) return;
        setAnalyses(list);
        setLoadError(null);
      },
      (error) => {
        if (!ignore) setLoadError(error instanceof Error ? error.message : "Couldn't load analyses.");
      },
    );
    return () => {
      ignore = true;
    };
  }, [reloadKey]);

  async function handleDelete(analysis: AnalysisSummary) {
    const confirmed = window.confirm(
      `Delete the analysis of "${analysis.filename}"? Its saved results and search index are removed, so analysing it again starts from scratch.`,
    );
    if (!confirmed) return;
    setDeleting(analysis.document_id);
    try {
      await deleteAnalysis(analysis.document_id);
      toast.success(`Deleted ${analysis.filename}`);
      setReloadKey((key) => key + 1);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Delete failed.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Past analyses</CardTitle>
        <CardDescription>Open a report, or delete one to free the space it uses.</CardDescription>
      </CardHeader>
      <CardContent>
        {loadError ? (
          <div className="flex flex-col items-start gap-2 text-sm">
            <p className="text-destructive">{loadError}</p>
            <Button variant="outline" size="sm" onClick={() => setReloadKey((key) => key + 1)}>
              Try again
            </Button>
          </div>
        ) : analyses === null ? (
          <p className="flex items-center gap-2 text-sm text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" /> Loading…
          </p>
        ) : analyses.length === 0 ? (
          <p className="text-sm text-muted-foreground">No analyses yet. Upload a DRHP or RHP to start one.</p>
        ) : (
          <ul className="flex flex-col divide-y">
            {analyses.map((analysis) => (
              <li key={analysis.document_id} className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
                <FileText className="size-5 shrink-0 text-muted-foreground" />
                <Link
                  href={`/analysis/${encodeURIComponent(analysis.document_id)}`}
                  className="min-w-0 flex-1 hover:underline"
                >
                  <span className="block truncate font-medium">{analysis.filename}</span>
                  <span className="block text-sm text-muted-foreground">
                    {analysis.page_count} pages · {formatDate(analysis.finished_at)}
                  </span>
                </Link>
                <span className="shrink-0 text-sm tabular-nums text-muted-foreground">{analysis.score.toFixed(1)}</span>
                <RatingBadge rating={analysis.rating} className="shrink-0" />
                <Button
                  variant="ghost"
                  size="icon-sm"
                  aria-label={`Delete ${analysis.filename}`}
                  disabled={deleting === analysis.document_id}
                  onClick={() => handleDelete(analysis)}
                >
                  {deleting === analysis.document_id ? <LoaderCircle className="animate-spin" /> : <Trash />}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
