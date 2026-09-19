// Number formatting, labels and colours shared by the IPO pages.
import type { Flag, Rating, Signal } from "@/lib/ipo";

const number = (value: number, digits: number) =>
  value.toLocaleString("en-IN", { minimumFractionDigits: digits, maximumFractionDigits: digits });

/** A metric value in the unit Agent 2 uses for it. */
export function formatMetric(value: number | null | undefined, unit: string): string {
  if (value === null || value === undefined) return "–";
  if (unit === "₹ m") return number(value, 1);
  if (unit === "%") return `${number(value, 1)}%`;
  if (unit === "x") return `${number(value, 2)}×`;
  return number(value, 0); // days
}

export const formatMillion = (value: number | null | undefined) =>
  value === null || value === undefined ? "–" : `₹${number(value, 1)} m`;

export const formatCount = (value: number | null | undefined) =>
  value === null || value === undefined ? "–" : number(value, 0);

export function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

// Agent 2's metrics: label and unit, in display order (mirrors ratios.py)
export const METRICS: Record<string, { label: string; unit: string }> = {
  revenue: { label: "Revenue from operations", unit: "₹ m" },
  revenue_growth: { label: "Revenue growth", unit: "%" },
  ebitda: { label: "EBITDA", unit: "₹ m" },
  ebitda_margin: { label: "EBITDA margin", unit: "%" },
  pat: { label: "Profit after tax", unit: "₹ m" },
  pat_margin: { label: "PAT margin", unit: "%" },
  roe: { label: "Return on equity", unit: "%" },
  debt_to_equity: { label: "Debt to equity", unit: "x" },
  interest_coverage: { label: "Interest coverage", unit: "x" },
  current_ratio: { label: "Current ratio", unit: "x" },
  receivable_days: { label: "Receivable days", unit: "days" },
  inventory_days: { label: "Inventory days", unit: "days" },
  operating_cash_flow: { label: "Operating cash flow", unit: "₹ m" },
  cash_conversion: { label: "Operating cash flow / PAT", unit: "x" },
  free_cash_flow: { label: "Free cash flow", unit: "₹ m" },
  other_income_share: { label: "Other income / profit before tax", unit: "%" },
};

export const RISK_CATEGORIES: Record<string, string> = {
  business: "Business",
  financial: "Financial",
  regulatory_legal: "Regulatory & legal",
  litigation: "Litigation",
  management: "Management & promoters",
  macroeconomic: "Macroeconomic",
  offer_shares: "Offer & shares",
};

export const CASE_TYPES: Record<string, string> = {
  criminal: "Criminal",
  regulatory: "Regulatory",
  sebi_disciplinary: "SEBI / exchange action",
  tax: "Tax",
  civil: "Civil & arbitration",
};

export const PARTIES: Record<string, string> = {
  company: "Company",
  subsidiary: "Subsidiary",
  promoter: "Promoter",
  director: "Director",
  group_company: "Group company",
  key_management: "Key management",
};

/** Words for a snake_case key the maps above don't cover. */
export const humanise = (key: string) => key.replaceAll("_", " ").replace(/^\w/, (c) => c.toUpperCase());

// Colour classes. Each pairs a light and a dark-mode variant.
export const RATING_STYLES: Record<Rating, string> = {
  "Leans Subscribe": "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  Neutral: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  "Leans Avoid": "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
};

export const SIGNAL_STYLES: Record<Signal, string> = {
  positive: "bg-emerald-100 text-emerald-900 dark:bg-emerald-950 dark:text-emerald-200",
  neutral: "bg-muted text-foreground",
  negative: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  unknown: "bg-muted text-muted-foreground",
};

export const FLAG_STYLES: Record<Flag["severity"], string> = {
  red: "border-red-300 bg-red-50 text-red-900 dark:border-red-900 dark:bg-red-950/60 dark:text-red-200",
  amber: "border-amber-300 bg-amber-50 text-amber-900 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200",
  info: "border-border bg-muted/50 text-foreground",
};

// Risk scores 1-5, from boilerplate (1) to a threat to the core business (5)
export const SCORE_STYLES: Record<number, string> = {
  5: "bg-red-600 text-white",
  4: "bg-red-100 text-red-900 dark:bg-red-950 dark:text-red-200",
  3: "bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200",
  2: "bg-muted text-foreground",
  1: "bg-muted text-muted-foreground",
};
