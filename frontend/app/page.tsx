"use client";

import { useState } from "react";
import { FileText } from "lucide-react";
import { toast } from "sonner";
import { ChatWindow } from "@/components/ChatWindow";
import { FileUpload } from "@/components/FileUpload";
import { DOMAINS, getDomain, type DomainId } from "@/lib/domains";
import type { IngestResult } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

// Documents uploaded during this browser session, grouped by domain.
// The backend has no "list documents" endpoint yet, so this resets on refresh.
type DocumentsByDomain = Record<DomainId, IngestResult[]>;

const EMPTY_DOCUMENTS: DocumentsByDomain = {
  legal: [],
  finance: [],
  healthcare: [],
  enterprise: [],
};

export default function Home() {
  const [activeDomain, setActiveDomain] = useState<DomainId>("legal");
  const [documents, setDocuments] = useState<DocumentsByDomain>(EMPTY_DOCUMENTS);

  function handleUploaded(result: IngestResult) {
    setDocuments((previous) => ({
      ...previous,
      // Re-uploading a file replaces its chunks on the backend, so replace it here too
      [result.domain]: [
        result,
        ...previous[result.domain].filter((doc) => doc.filename !== result.filename),
      ],
    }));

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

                <Card size="sm">
                  <CardHeader>
                    <CardTitle>Indexed this session</CardTitle>
                  </CardHeader>
                  <CardContent>
                    {documents[domain.id].length === 0 ? (
                      <p className="text-muted-foreground">
                        No {domain.label.toLowerCase()} documents uploaded yet.
                      </p>
                    ) : (
                      <ul className="flex flex-col gap-2">
                        {documents[domain.id].map((doc) => (
                          <li key={doc.filename} className="flex items-center gap-2">
                            <FileText className="size-4 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 flex-1 truncate" title={doc.filename}>
                              {doc.filename}
                            </span>
                            <Badge variant="secondary">
                              {doc.chunks_stored} chunk{doc.chunks_stored === 1 ? "" : "s"}
                            </Badge>
                          </li>
                        ))}
                      </ul>
                    )}
                  </CardContent>
                </Card>
              </div>

              <ChatWindow domain={domain.id} />
            </div>
          </TabsContent>
        ))}
      </Tabs>
    </main>
  );
}
