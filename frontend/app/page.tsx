"use client";

import { useEffect, useState } from "react";
import { toast } from "sonner";
import { ChatWindow } from "@/components/ChatWindow";
import { DocumentList } from "@/components/DocumentList";
import { FileUpload } from "@/components/FileUpload";
import { DOMAINS, getDomain, type DomainId } from "@/lib/domains";
import { listDocuments, type IngestResult, type StoredDocument } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export default function Home() {
  const [activeDomain, setActiveDomain] = useState<DomainId>("legal");
  // Every document stored on the backend, across all domains.
  // null until the first load finishes.
  const [documents, setDocuments] = useState<StoredDocument[] | null>(null);
  const [documentsError, setDocumentsError] = useState<string | null>(null);
  // Bumping this number re-runs the effect below, which reloads the list
  const [reloadKey, setReloadKey] = useState(0);
  const refreshDocuments = () => setReloadKey((key) => key + 1);

  // Load the document list when the page opens, and again after every refresh.
  useEffect(() => {
    // If a newer reload starts before this one finishes, ignore this result,
    // so a slow, older response can't overwrite a newer list.
    let ignore = false;
    listDocuments().then(
      (docs) => {
        if (ignore) return;
        setDocuments(docs);
        setDocumentsError(null);
      },
      (error) => {
        if (ignore) return;
        setDocumentsError(error instanceof Error ? error.message : "Couldn't load documents.");
      },
    );
    return () => {
      ignore = true;
    };
  }, [reloadKey]);

  function handleUploaded(result: IngestResult) {
    refreshDocuments();

    // Auto-detection may file the document under a different domain than
    // the open tab. Follow it, so the user can immediately ask about it.
    if (result.domain !== activeDomain) {
      setActiveDomain(result.domain);
      toast.info(`Detected as ${getDomain(result.domain).label}. Switched tabs.`);
    }
  }

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">Agentic RAG</h1>
        <p className="text-muted-foreground">
          Upload a document, then ask questions. Answers cite the exact source pages.
        </p>
      </header>

      <Tabs
        value={activeDomain}
        onValueChange={(value) => setActiveDomain(value as DomainId)}
      >
        <TabsList className="w-full sm:w-fit">
          {DOMAINS.map((domain) => (
            <TabsTrigger key={domain.id} value={domain.id} className="sm:px-3">
              <domain.icon className="hidden sm:block" />
              {domain.label}
            </TabsTrigger>
          ))}
        </TabsList>

        {DOMAINS.map((domain) => (
          // keepMounted hides inactive tabs instead of removing them, so each
          // domain's chat history survives switching tabs.
          <TabsContent key={domain.id} value={domain.id} keepMounted className="pt-2">
            <p className="mb-4 text-muted-foreground">{domain.description}</p>

            <div className="grid gap-6 lg:grid-cols-[minmax(0,360px)_minmax(0,1fr)]">
              <div className="flex flex-col gap-6">
                <FileUpload activeDomain={domain.id} onUploaded={handleUploaded} />

                <DocumentList
                  domain={domain.id}
                  documents={documents && documents.filter((doc) => doc.domain === domain.id)}
                  loadError={documentsError}
                  onChanged={refreshDocuments}
                />
              </div>

              <ChatWindow domain={domain.id} />
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </main>
  );
}
