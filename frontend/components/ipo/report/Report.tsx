"use client";

import Link from "next/link";
import { ExternalLink, TriangleAlert } from "lucide-react";
import { formatDate } from "@/lib/format";
import { documentUrl, type Analysis } from "@/lib/ipo";
import { Card, CardContent } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { RatingBadge } from "@/components/ipo/RatingBadge";
import { BusinessDetails } from "@/components/ipo/report/BusinessDetails";
import { FinancialDetails } from "@/components/ipo/report/FinancialDetails";
import { LegalDetails } from "@/components/ipo/report/LegalDetails";
import { OfferDetails } from "@/components/ipo/report/OfferDetails";
import { ReportChat } from "@/components/ipo/report/ReportChat";
import { RiskDetails } from "@/components/ipo/report/RiskDetails";
import { ScoreBreakdown } from "@/components/ipo/report/ScoreBreakdown";
import { Summary } from "@/components/ipo/report/Summary";
import { DocumentContext } from "@/components/ipo/report/shared";

const FALLBACK_DISCLAIMER =
  "This is an educational analysis generated automatically from the offer document by AI models. It may contain errors and is not investment advice.";

export function Report({ analysis }: { analysis: Analysis }) {
  const { results } = analysis;
  const score = results.score;

  return (
    <DocumentContext value={{ documentId: analysis.document_id, pageOffset: analysis.page_offset }}>
      <div className="flex flex-col gap-6">
        <Link href="/" className="text-sm text-muted-foreground hover:text-foreground">
          ← All analyses
        </Link>

        <header className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 flex-col gap-1">
            <h1 className="truncate text-2xl font-semibold tracking-tight">{analysis.filename}</h1>
            <p className="text-sm text-muted-foreground">
              {analysis.page_count} pages · analysed {formatDate(analysis.finished_at)} ·{" "}
              <a
                href={documentUrl(analysis.document_id)}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 hover:text-foreground"
              >
                open the document <ExternalLink className="size-3" />
              </a>
            </p>
          </div>
          {score && (
            <div className="flex shrink-0 items-center gap-3">
              <span className="text-3xl font-semibold tabular-nums">
                {score.score.toFixed(1)}
                <span className="text-base font-normal text-muted-foreground"> / 100</span>
              </span>
              <div className="flex flex-col items-start gap-1">
                <RatingBadge rating={score.rating} />
                <span className="text-xs text-muted-foreground">{score.risk_reward.quadrant}</span>
              </div>
            </div>
          )}
        </header>

        {score && (score.knockouts.length > 0 || score.incomplete.length > 0) && (
          <Card size="sm">
            <CardContent className="flex gap-2 text-sm">
              <TriangleAlert className="mt-0.5 size-4 shrink-0 text-amber-600" />
              <div className="flex flex-col gap-1">
                {score.knockouts.map((reason) => (
                  <p key={reason}>Rating capped at Neutral: {reason}.</p>
                ))}
                {score.incomplete.length > 0 && (
                  <p>
                    Incomplete: {score.incomplete.join(", ")} didn&apos;t finish, so each got half marks.
                  </p>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        <p className="text-xs text-muted-foreground">{results.report?.disclaimer ?? FALLBACK_DISCLAIMER}</p>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,380px)]">
          <Summary report={results.report} />
          {score && <ScoreBreakdown score={score} />}
        </div>

        <Tabs defaultValue="ask">
          <TabsList className="w-full flex-wrap sm:w-fit">
            <TabsTrigger value="ask">Ask a question</TabsTrigger>
            <TabsTrigger value="financial">Financials</TabsTrigger>
            <TabsTrigger value="risk">
              Risk factors{results.risk?.counts ? ` (${results.risk.counts.total})` : ""}
            </TabsTrigger>
            <TabsTrigger value="business">Business & promoters</TabsTrigger>
            <TabsTrigger value="offer">Offer</TabsTrigger>
            <TabsTrigger value="legal">Legal</TabsTrigger>
          </TabsList>
          <Card className="mt-2">
            <CardContent>
              {/* keepMounted: the conversation survives switching tabs */}
              <TabsContent value="ask" keepMounted>
                <ReportChat documentId={analysis.document_id} />
              </TabsContent>
              <TabsContent value="financial">
                <FinancialDetails financial={results.financial} />
              </TabsContent>
              <TabsContent value="risk">
                <RiskDetails risk={results.risk} />
              </TabsContent>
              <TabsContent value="business">
                <BusinessDetails business={results.business} />
              </TabsContent>
              <TabsContent value="offer">
                <OfferDetails offer={results.offer} />
              </TabsContent>
              <TabsContent value="legal">
                <LegalDetails legal={results.legal} />
              </TabsContent>
            </CardContent>
          </Card>
        </Tabs>
      </div>
    </DocumentContext>
  );
}
