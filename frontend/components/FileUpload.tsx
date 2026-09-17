"use client";

import { useRef, useState } from "react";
import { CloudUpload, LoaderCircle } from "lucide-react";
import { toast } from "sonner";
import { cn } from "@/lib/utils";
import { MAX_UPLOAD_MB, uploadDocument, type IngestResult } from "@/lib/api";
import { getDomain, type DomainId } from "@/lib/domains";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];

type FileUploadProps = {
  activeDomain: DomainId;
  onUploaded: (result: IngestResult) => void;
};

export function FileUpload({ activeDomain, onUploaded }: FileUploadProps) {
  const [autoDetect, setAutoDetect] = useState(true);
  const [isUploading, setIsUploading] = useState(false);
  const [isDragging, setIsDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    // Reject wrong types here too: the file picker's `accept` filter is only
    // a hint, and drag-and-drop bypasses it entirely.
    const extension = file.name.slice(file.name.lastIndexOf(".")).toLowerCase();
    if (!ACCEPTED_EXTENSIONS.includes(extension)) {
      toast.error(`"${file.name}" isn't supported. Upload a PDF, DOCX, or TXT file.`);
      return;
    }

    // Check the size before uploading, so a huge file fails instantly
    // instead of after a long upload the backend would reject anyway.
    const sizeMb = file.size / (1024 * 1024);
    if (sizeMb > MAX_UPLOAD_MB) {
      toast.error(`"${file.name}" is ${sizeMb.toFixed(1)} MB. The limit is ${MAX_UPLOAD_MB} MB.`);
      return;
    }

    setIsUploading(true);
    try {
      // null tells the backend to detect the domain from the document's text
      const result = await uploadDocument(file, autoDetect ? null : activeDomain);
      const chunks = `${result.chunks_stored} chunk${result.chunks_stored === 1 ? "" : "s"}`;
      toast.success(
        `Indexed ${result.filename}: ${chunks} in ${getDomain(result.domain).label}`,
        // The keyword fallback is less accurate, so ask the user to double-check
        result.detected_by === "keywords"
          ? {
              description:
                "The AI classifier was unavailable, so the domain was guessed from keywords. Check it's right.",
            }
          : undefined,
      );
      onUploaded(result);
    } catch (error) {
      // ApiError messages come from the backend and already explain the problem
      toast.error(error instanceof Error ? error.message : "Upload failed.");
    } finally {
      setIsUploading(false);
      // Clear the input so choosing the same file again still fires onChange
      if (inputRef.current) inputRef.current.value = "";
    }
  }

  function handleDrop(event: React.DragEvent<HTMLLabelElement>) {
    event.preventDefault(); // stop the browser from opening the dropped file
    setIsDragging(false);
    const file = event.dataTransfer.files[0];
    if (file && !isUploading) handleFile(file);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Upload a document</CardTitle>
        <CardDescription>
          PDF, DOCX, or TXT, up to {MAX_UPLOAD_MB} MB. Tables are extracted too.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-col gap-3">
        {/* A <label> wrapping the hidden input makes the whole box clickable
            and keyboard-accessible without any extra JavaScript. */}
        <label
          onDragOver={(event) => {
            event.preventDefault(); // required, or the browser won't allow a drop
            setIsDragging(true);
          }}
          onDragLeave={() => setIsDragging(false)}
          onDrop={handleDrop}
          className={cn(
            "flex cursor-pointer flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
            "focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50",
            isDragging ? "border-primary bg-muted" : "border-border hover:bg-muted/50",
            isUploading && "pointer-events-none opacity-60",
          )}
        >
          <input
            ref={inputRef}
            type="file"
            accept={ACCEPTED_EXTENSIONS.join(",")}
            className="sr-only"
            disabled={isUploading}
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFile(file);
            }}
          />
          {isUploading ? (
            <>
              <LoaderCircle className="size-6 animate-spin text-muted-foreground" />
              <span className="font-medium">Parsing and indexing…</span>
              <span className="text-xs text-muted-foreground">
                Large PDFs can take a little while.
              </span>
            </>
          ) : (
            <>
              <CloudUpload className="size-6 text-muted-foreground" />
              <span className="font-medium">Drop a file here or click to browse</span>
              <span className="text-xs text-muted-foreground">
                {autoDetect
                  ? "The domain will be detected automatically"
                  : `Will be stored under ${getDomain(activeDomain).label}`}
              </span>
            </>
          )}
        </label>

        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={autoDetect}
            onChange={(event) => setAutoDetect(event.target.checked)}
            className="size-4 accent-primary"
          />
          Auto-detect domain from content
        </label>
      </CardContent>
    </Card>
  );
}
