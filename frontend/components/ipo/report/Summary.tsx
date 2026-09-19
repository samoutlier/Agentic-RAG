"use client";

import { TrendingDown, TrendingUp } from "lucide-react";
import type { ReportResult } from "@/lib/ipo";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { AgentFooter, PageLinks, SectionTitle, Unavailable } from "@/components/ipo/report/shared";

export function Summary({ report }: { report: ReportResult | null }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Summary</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {!report?.executive_summary ? (
          <Unavailable what="written summary" output={report} />
        ) : (
          <>
            <p className="leading-relaxed">{report.executive_summary}</p>

            <div className="grid gap-6 md:grid-cols-2">
              {[
                { title: "Bull case", points: report.bull_case ?? [], Icon: TrendingUp, tone: "text-emerald-600" },
                { title: "Bear case", points: report.bear_case ?? [], Icon: TrendingDown, tone: "text-red-600" },
              ].map(({ title, points, Icon, tone }) => (
                <section key={title} className="flex flex-col gap-2">
                  <SectionTitle>
                    <span className="flex items-center gap-1.5">
                      <Icon className={`size-4 ${tone}`} /> {title}
                    </span>
                  </SectionTitle>
                  <ul className="flex flex-col gap-3 text-sm">
                    {points.map((point, i) => (
                      <li key={i}>
                        {point.text} <PageLinks pages={point.pages} />
                      </li>
                    ))}
                  </ul>
                </section>
              ))}
            </div>

            {(report.check_before_investing ?? []).length > 0 && (
              <section className="flex flex-col gap-2">
                <SectionTitle>Worth checking before deciding</SectionTitle>
                <ul className="flex list-disc flex-col gap-1 pl-5 text-sm">
                  {report.check_before_investing!.map((item, i) => (
                    <li key={i}>{item}</li>
                  ))}
                </ul>
              </section>
            )}
          </>
        )}
        <AgentFooter output={report} />
      </CardContent>
    </Card>
  );
}
