// Types and API calls for the IPO analysis. The types mirror the JSON the
// backend's agents produce (backend/app/agents/*.py), so a renamed field
// there shows up here as a type error instead of a silently empty page.
import { API_URL, request } from "@/lib/api";

// ── Jobs: an analysis running in the background ──

export const STEP_NAMES = [
  "parse", "index", "risk", "financial", "legal", "business", "offer", "score", "synthesis",
] as const;
export type StepName = (typeof STEP_NAMES)[number];
export type StepStatus = "waiting" | "running" | "done" | "failed";

export type JobEvent = {
  agent: string;
  event: "started" | "progress" | "waiting" | "done" | "failed";
  message: string;
  at: number; // seconds since the job was created
};

export type Job = {
  id: string;
  document_id: string;
  filename: string;
  status: "queued" | "running" | "done" | "failed";
  steps: Record<StepName, StepStatus>;
  events: JobEvent[]; // only the events after the `after` we asked for
  event_count: number;
  queue_position: number;
  error: string | null;
  created_at: number; // Unix seconds
  finished_at: number | null;
};

// ── A finished analysis ──

export type Rating = "Leans Subscribe" | "Neutral" | "Leans Avoid";

// A statement and the printed page numbers that support it
export type Cited = { text: string; pages: number[] };

export type Flag = {
  severity: "red" | "amber" | "info";
  code: string;
  message: string;
  metrics?: string[];
};

// Fields every agent's output has
type AgentOutput = {
  status: "done" | "failed";
  model: string;
  tokens: number;
  seconds: number;
  error?: string;
  warnings?: string[];
};

export type RiskItem = {
  rank: number;
  number: number;
  text: string;
  page: number;
  group: string | null;
  headline: string;
  category: string | null;
  score: number | null;
  severity: "high" | "medium" | "low" | null;
};

export type RiskResult = AgentOutput & {
  register?: RiskItem[];
  counts?: {
    total: number;
    by_score: Record<string, number>;
    by_severity: Record<"high" | "medium" | "low", number>;
    by_category: Record<string, number>;
    average_score: number | null;
  };
};

export type Period = { label: string; full_year: boolean };
export type Signal = "positive" | "neutral" | "negative" | "unknown";

export type FinancialResult = AgentOutput & {
  unit?: string;
  reported_unit?: string;
  periods?: Period[]; // newest first
  metrics?: Record<string, Record<string, number | null>>;
  growth?: Record<string, number | string | null>;
  scorecard?: { dimension: string; signal: Signal; reason: string }[];
  flags?: Flag[];
  pages?: Record<string, number>;
  assessment?: {
    summary: string;
    strengths: { point: string; metrics: string[] }[];
    concerns: { point: string; metrics: string[] }[];
  };
};

export type BusinessResult = AgentOutput & {
  profile?: {
    description: Cited | null;
    strengths: Cited[];
    weaknesses: Cited[];
    market_position: Cited | null;
  };
  promoters?: {
    people: { name: string; role: string; background: string | null; pages: number[] }[];
    pre_offer_holding_pct: number | null;
    holding_pages: number[];
    holding_signal: { level: "high" | "moderate" | "low" | "unknown"; reason: string };
    shares_pledged: boolean | null;
    pledge_source: Cited;
    related_party: Cited | null;
    governance_concerns: Cited[];
  };
};

export type OfferResult = AgentOutput & {
  structure?: {
    amount_unit: "million" | "lakh" | "crore";
    fresh_issue_amount: number | null;
    fresh_issue_shares: number | null;
    offer_for_sale_shares: number | null;
    selling_shareholders: string[];
    promoters_selling: boolean;
    shares_before_offer: number | null;
    shares_after_offer: number | null;
    objects: { purpose: string; amount: number | null; pages: number[] }[];
    general_corporate_purposes_amount: number | null;
    pages: number[];
  };
  metrics?: Record<string, number | null>;
  flags?: Flag[];
  peers?: {
    peers: { name: string; pe: number | null; eps: number | null; ronw_pct: number | null }[];
    peer_pe_high: number | null;
    peer_pe_low: number | null;
    peer_pe_average: number | null;
    company_ronw_pct: number | null;
    company_nav_per_share: number | null;
    pages: number[];
  };
};

export type LegalCase = {
  heading: string;
  party: string;
  against_party: boolean;
  type: "criminal" | "regulatory" | "sebi_disciplinary" | "tax" | "civil";
  total_row: boolean;
  in_total_row: boolean;
  count: number;
  amount_million: number | null;
  summary: string;
  page: number;
};

export type LegalResult = AgentOutput & {
  cases?: LegalCase[];
  summary?: {
    against_by_type: Record<LegalCase["type"], { count: number; amount_million: number }>;
    total_amount_against_million: number;
    net_worth_million: number | null;
    amount_pct_of_net_worth: number | null;
    filed_by_parties: number;
  };
  approvals?: {
    all_material_obtained: boolean | null;
    pending: string[];
    not_applied: string[];
    pages: number[];
  };
  flags?: Flag[];
};

export type ScorePart = {
  name: string;
  label: string;
  points: number;
  max_points: number;
  reasons: string[];
  complete: boolean;
};

export type ScoreResult = {
  score: number;
  rating: Rating;
  knockouts: string[];
  parts: ScorePart[];
  incomplete: string[];
  risk_reward: { reward: number; safety: number; quadrant: string };
};

export type ReportPoint = { text: string; facts: string[]; pages: number[] };

export type ReportResult = AgentOutput & {
  rating: Rating;
  score: number;
  disclaimer: string;
  facts: { id: string; text: string; pages: number[] }[];
  executive_summary?: string;
  bull_case?: ReportPoint[];
  bear_case?: ReportPoint[];
  check_before_investing?: string[];
};

export type AnalysisSummary = {
  document_id: string;
  filename: string;
  page_count: number;
  finished_at: string; // ISO date
  score: number;
  rating: Rating;
  agents: Record<string, "done" | "failed" | null>;
};

export type Analysis = AnalysisSummary & {
  page_offset: number;
  sections: { title: string; key: string | null; start_page: number; end_page: number }[];
  results: {
    risk: RiskResult | null;
    financial: FinancialResult | null;
    legal: LegalResult | null;
    business: BusinessResult | null;
    offer: OfferResult | null;
    score: ScoreResult | null;
    report: ReportResult | null;
  };
};

// ── API calls ──

type Started = { job_id: string; document_id: string; status: Job["status"] };

/** Upload a DRHP / RHP and queue its analysis. `fresh` redoes every agent. */
export async function startAnalysis(file: File, fresh: boolean): Promise<Started> {
  const form = new FormData();
  form.append("file", file);
  if (fresh) form.append("fresh", "true");
  const response = await request("/ipo/analyses", { method: "POST", body: form });
  return response.json();
}

/** Analyse an already-uploaded document again; saved agent outputs are reused. */
export async function rerunAnalysis(documentId: string): Promise<Started> {
  const response = await request(`/ipo/analyses/${encodeURIComponent(documentId)}/rerun`, { method: "POST" });
  return response.json();
}

/** A job's progress. Pass the event_count you last saw to get only new events. */
export async function getJob(jobId: string, after: number): Promise<Job> {
  const response = await request(`/ipo/jobs/${encodeURIComponent(jobId)}?after=${after}`);
  return response.json();
}

export async function listAnalyses(): Promise<AnalysisSummary[]> {
  const response = await request("/ipo/analyses");
  return response.json();
}

export async function getAnalysis(documentId: string): Promise<Analysis> {
  const response = await request(`/ipo/analyses/${encodeURIComponent(documentId)}`);
  return response.json();
}

export async function deleteAnalysis(documentId: string): Promise<void> {
  await request(`/ipo/analyses/${encodeURIComponent(documentId)}`, { method: "DELETE" });
}

/** The uploaded PDF, served by the backend for viewing in the browser. */
export function documentUrl(documentId: string): string {
  return `${API_URL}/ipo/analyses/${encodeURIComponent(documentId)}/document`;
}

/** A link that opens the uploaded PDF at a printed page number. The
 * browser's PDF viewer counts pages from the cover, 1-based. */
export function pageUrl(documentId: string, printedPage: number, pageOffset: number): string {
  return `${documentUrl(documentId)}#page=${printedPage + pageOffset + 1}`;
}
