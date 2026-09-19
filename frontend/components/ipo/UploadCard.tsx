"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { CloudUpload, LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { MAX_UPLOAD_MB } from "@/lib/api";
import { startAnalysis } from "@/lib/ipo";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

export function UploadCard() {
  const router = useRouter();
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const [fresh, setFresh] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    // The picker's `accept` filter is only a hint, and drag-and-drop skips it
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      toast.error(`"${file.name}" isn't a PDF. Upload the DRHP or RHP as a PDF.`);
      return;
    }
    const sizeMb = file.size / (1024 * 1024);
    if (sizeMb > MAX_UPLOAD_MB) {
      toast.error(`"${file.name}" is ${sizeMb.toFixed(1)} MB. The limit is ${MAX_UPLOAD_MB} MB.`);
      return;
    }

    setIsUploading(true);
    try {
      const { job_id, document_id } = await startAnalysis(file, fresh);
      // The job id goes in the URL, so a refresh reconnects to the same job
      router.push(`/analysis/${encodeURIComponent(document_id)}?job=${job_id}`);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Upload failed.");
      setIsUploading(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Analyse an IPO</CardTitle>
        <CardDescription>
          Upload a Draft Red Herring Prospectus (DRHP) or Red Herring Prospectus (RHP), up to {MAX_UPLOAD_MB} MB.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <button
          type="button"
          disabled={isUploading}
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => {
            event.preventDefault(); // allows the drop
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={(event) => {
            event.preventDefault();
            setIsDragging(false);
            const file = event.dataTransfer.files[0];
            if (file) handleFile(file);
          }}
          className={cn(
            "flex flex-col items-center gap-2 rounded-lg border-2 border-dashed px-4 py-10 text-center transition-colors",
            "hover:border-foreground/30 hover:bg-muted/40 disabled:cursor-wait disabled:opacity-70",
            isDragging && "border-foreground/40 bg-muted/60",
          )}
        >
          {isUploading ? (
            <LoaderCircle className="size-8 animate-spin text-muted-foreground" />
          ) : (
            <CloudUpload className="size-8 text-muted-foreground" />
          )}
          <span className="font-medium">
            {isUploading ? "Uploading…" : "Drop the PDF here, or click to choose"}
          </span>
          <span className="text-sm text-muted-foreground">
            A new document takes about 5–8 minutes; one analysed before loads in seconds.
          </span>
        </button>
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,application/pdf"
          className="hidden"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) handleFile(file);
            event.target.value = ""; // lets the same file be chosen again
          }}
        />
        <label className="flex items-start gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={fresh}
            onChange={(event) => setFresh(event.target.checked)}
            className="mt-0.5"
          />
          <span>
            Redo every agent, even if this document was analysed before (uses more of the free Groq quota)
          </span>
        </label>
      </CardContent>
    </Card>
  );
}
