"use client";

import type { BusinessResult } from "@/lib/ipo";
import { AgentFooter, CitedList, CitedText, PageLinks, SectionTitle, Unavailable } from "@/components/ipo/report/shared";

const HOLDING_WORDS = { high: "High stake", moderate: "Moderate stake", low: "Low stake", unknown: "Stake not stated" };

export function BusinessDetails({ business }: { business: BusinessResult | null }) {
  const profile = business?.profile;
  const promoters = business?.promoters;
  if (!profile && !promoters) return <Unavailable what="business and promoter analysis" output={business} />;

  return (
    <div className="flex flex-col gap-6">
      {profile && (
        <div className="flex flex-col gap-5">
          {profile.description && (
            <p className="leading-relaxed">
              <CitedText item={profile.description} />
            </p>
          )}
          <div className="grid gap-6 md:grid-cols-2">
            <section className="flex flex-col gap-2 text-sm">
              <SectionTitle>Strengths</SectionTitle>
              <CitedList items={profile.strengths} empty="None the excerpts back with facts." />
            </section>
            <section className="flex flex-col gap-2 text-sm">
              <SectionTitle>Weaknesses and dependencies</SectionTitle>
              <CitedList items={profile.weaknesses} empty="None found." />
            </section>
          </div>
          {profile.market_position && (
            <p className="text-sm">
              <span className="font-medium">Market position: </span>
              <CitedText item={profile.market_position} />
            </p>
          )}
        </div>
      )}

      {promoters && (
        <section className="flex flex-col gap-4 border-t pt-5">
          <SectionTitle>Promoters</SectionTitle>
          <ul className="grid gap-3 sm:grid-cols-2">
            {promoters.people.map((person) => (
              <li key={person.name} className="rounded-md border p-3 text-sm">
                <p className="font-medium">{person.name}</p>
                <p className="text-muted-foreground">{person.role}</p>
                {person.background && <p className="mt-1">{person.background}</p>}
                <PageLinks pages={person.pages} className="mt-1" />
              </li>
            ))}
          </ul>
          <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-[12rem_1fr]">
            <dt className="text-muted-foreground">Holding</dt>
            <dd>
              {HOLDING_WORDS[promoters.holding_signal.level]}: {promoters.holding_signal.reason}{" "}
              <PageLinks pages={promoters.holding_pages} />
            </dd>
            <dt className="text-muted-foreground">Shares pledged</dt>
            <dd>
              {promoters.shares_pledged === null ? "Not stated" : promoters.shares_pledged ? "Yes" : "No"}
              {promoters.pledge_source.pages.length > 0 && (
                <>
                  {" "}
                  (&ldquo;{promoters.pledge_source.text}&rdquo;) <PageLinks pages={promoters.pledge_source.pages} />
                </>
              )}
            </dd>
            <dt className="text-muted-foreground">Related-party dealings</dt>
            <dd>{promoters.related_party ? <CitedText item={promoters.related_party} /> : "Not summarised"}</dd>
            <dt className="text-muted-foreground">Governance concerns</dt>
            <dd>
              <CitedList items={promoters.governance_concerns} empty="None found in the excerpts." />
            </dd>
          </dl>
        </section>
      )}

      <AgentFooter output={business} />
    </div>
  );
}
