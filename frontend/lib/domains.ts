import { Building, HeartPulse, Landmark, Scale, type LucideIcon } from "lucide-react";

// Must match the domain keys in backend/app/config.py (DOMAIN_COLLECTIONS)
export type DomainId = "legal" | "finance" | "healthcare" | "enterprise";

export type Domain = {
  id: DomainId;
  label: string;
  description: string;
  icon: LucideIcon;
};

export const DOMAINS: Domain[] = [
  {
    id: "legal",
    label: "Legal",
    description: "Contract analysis, compliance checks, and clause extraction.",
    icon: Scale,
  },
  {
    id: "finance",
    label: "Finance",
    description: "Risk analysis, regulatory document review, and audit support.",
    icon: Landmark,
  },
  {
    id: "healthcare",
    label: "Healthcare",
    description: "Medical research summaries and clinical study analysis.",
    icon: HeartPulse,
  },
  {
    id: "enterprise",
    label: "Enterprise",
    description: "Internal policy Q&A, knowledge base search, and training docs.",
    icon: Building,
  },
];

export function getDomain(id: DomainId): Domain {
  return DOMAINS.find((domain) => domain.id === id) ?? DOMAINS[0];
}
