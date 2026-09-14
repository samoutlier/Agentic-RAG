import re
from app.config import DOMAIN_COLLECTIONS

# Keywords that signal each domain
DOMAIN_KEYWORDS = {
    "legal": [
        "contract", "clause", "agreement", "liability", "indemnity",
        "jurisdiction", "arbitration", "warranty", "termination",
        "confidentiality", "plaintiff", "defendant", "statute",
        "compliance", "regulation", "legal", "law", "court",
        "attorney", "counsel", "tort", "negligence", "breach",
    ],
    "finance": [
        "revenue", "profit", "loss", "balance sheet", "cash flow",
        "audit", "tax", "investment", "portfolio", "risk",
        "dividend", "equity", "debt", "interest rate", "fiscal",
        "financial", "bank", "loan", "credit", "asset",
        "liability", "shareholder", "quarterly", "annual report",
    ],
    "healthcare": [
        "patient", "diagnosis", "treatment", "clinical", "medical",
        "hospital", "drug", "therapy", "symptom", "disease",
        "health", "pharmaceutical", "dosage", "trial", "FDA",
        "surgery", "nurse", "physician", "pathology", "radiology",
        "oncology", "cardiology", "epidemiology", "vaccine",
    ],
    "enterprise": [
        "policy", "employee", "HR", "onboarding", "training",
        "procedure", "guideline", "workflow", "SOP", "handbook",
        "department", "organization", "management", "operations",
        "strategy", "KPI", "performance", "compliance", "memo",
        "internal", "corporate", "team", "project",
    ],
}


# Pre-compile one whole-word pattern per keyword.
# Word boundaries matter: a plain substring search would count "HR" inside
# "through", "law" inside "flaw", and "tax" inside "syntax" — common words
# that would skew every document toward the wrong domain.
DOMAIN_PATTERNS = {
    domain: [re.compile(rf"\b{re.escape(kw.lower())}\b") for kw in keywords]
    for domain, keywords in DOMAIN_KEYWORDS.items()
}


def detect_domain(text: str) -> str:
    """Detect document domain by counting distinct keyword matches.
    Falls back to 'enterprise' if nothing matches."""
    text_lower = text.lower()

    scores = {
        domain: sum(1 for pattern in patterns if pattern.search(text_lower))
        for domain, patterns in DOMAIN_PATTERNS.items()
    }

    best_domain = max(scores, key=scores.get)

    if scores[best_domain] == 0:
        return "enterprise"

    return best_domain


def validate_domain(domain: str) -> bool:
    """Check if a domain string is valid."""
    return domain in DOMAIN_COLLECTIONS
