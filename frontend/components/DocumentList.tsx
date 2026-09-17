"use client";

import { useState } from "react";
import { FileText, LoaderCircle, Trash } from "lucide-react";
import { toast } from "sonner";
import { deleteDocument, type StoredDocument } from "@/lib/api";
import { getDomain, type DomainId } from "@/lib/domains";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type DocumentListProps = {
  domain: DomainId;
  documents: StoredDocument[] | null; // null while the list is loading
  loadError: string | null;
  onChanged: () => void; // asks the page to reload the list
};

export function DocumentList({ domain, documents, loadError, onChanged }: DocumentListProps) {
  // Filename being deleted, so only that row shows a spinner
  const [deleting, setDeleting] = useState<string | null>(null);
  const label = getDomain(domain).label;

  async function handleDelete(filename: string) {
    // Deleting can't be undone, so ask first
    const confirmed = window.confirm(
      `Delete "${filename}" from ${label} documents? This can't be undone.`,
    );
    if (!confirmed) return;

    setDeleting(filename);
    try {
      await deleteDocument(domain, filename);
      toast.success(`Deleted ${filename}`);
      onChanged();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Delete failed.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{label} documents</CardTitle>
      </CardHeader>
      <CardContent>
        {loadError ? (
          <div className="flex flex-col items-start gap-2">
            <p role="alert" className="text-destructive">
              {loadError}
            </p>
            <Button variant="outline" size="sm" onClick={onChanged}>
              Try again
            </Button>
          </div>
        ) : documents === null ? (
          <p className="flex items-center gap-2 text-muted-foreground">
            <LoaderCircle className="size-4 animate-spin" />
            Loading documents…
          </p>
        ) : documents.length === 0 ? (
          <p className="text-muted-foreground">No {label.toLowerCase()} documents yet.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {documents.map((doc) => (
              <li key={doc.filename} className="flex items-center gap-2">
                <FileText className="size-4 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate" title={doc.filename}>
                  {doc.filename}
                </span>
                <Badge variant="secondary">
                  {doc.chunks} chunk{doc.chunks === 1 ? "" : "s"}
                </Badge>
                <Button
                  variant="ghost"
                  size="icon-sm"
                  onClick={() => handleDelete(doc.filename)}
                  disabled={deleting !== null}
                  aria-label={`Delete ${doc.filename}`}
                  title="Delete"
                >
                  {deleting === doc.filename ? (
                    <LoaderCircle className="animate-spin" />
                  ) : (
                    <Trash />
                  )}
                </Button>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
