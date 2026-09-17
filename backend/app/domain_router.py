import logging
import re
from app.config import DOMAIN_COLLECTIONS
from app.llm import classifier_llm

logger = logging.getLogger(__name__)


# ── LLM classification (primary) ──

# The opening of a document (title, parties, abstract, headings) almost
# always reveals what kind of document it is, so the model reads only this much.
CLASSIFIER_SAMPLE_CHARS = 3000

CLASSIFIER_PROMPT = """Classify the document below into exactly one category:
- legal: contracts, agreements, deeds, court filings, regulations
- finance: financial statements, quarterly or annual reports, audits, investment or risk analysis
- healthcare: medical research, clinical studies, patient care, drugs
- enterprise: internal company policies, procedures, HR, training, and anything that fits none of the above

Judge by what kind of document it is, not only the topics it mentions.

Filename: {filename}
Document start:
\"\"\"
{text}
\"\"\"

Reply with exactly one word: legal, finance, healthcare, or enterprise."""


def parse_domain_label(reply: str) -> str | None:
    """Pull a valid domain out of the model's reply, or None if it's unclear.

    Models sometimes add punctuation or a short sentence ("legal." or
    "The category is legal"), so accept any reply that names exactly one
    domain. A reply naming none or several is treated as a failure.
    """
    words = re.findall(r"[a-z]+", reply.lower())
    named = {word for word in words if word in DOMAIN_COLLECTIONS}
    return named.pop() if len(named) == 1 else None


def classify_domain_with_llm(text: str, filename: str) -> str | None:
    """Ask the classifier model for the document's domain. Returns None on any failure.

    The document text is untrusted and could contain instructions aimed at
    the model, but the worst outcome is a wrong category: the reply is only
    ever accepted if it is one of the four known domain names.
    """
    prompt = CLASSIFIER_PROMPT.format(filename=filename, text=text[:CLASSIFIER_SAMPLE_CHARS])
    try:
        reply = classifier_llm.invoke(prompt).content
    except Exception as exc:
        # Rate limit, bad key, timeout, no network: all mean "use the fallback"
        logger.warning("LLM domain classification failed, falling back to keywords: %r", exc)
        return None

    domain = parse_domain_label(reply)
    if domain is None:
        logger.warning("Unclear classifier reply %r, falling back to keywords", reply[:100])
    return domain


# ── Keyword matching (fallback) ──

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


def detect_domain_by_keywords(text: str) -> str:
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


# ── Entry point ──


def detect_domain(text: str, filename: str = "") -> tuple[str, str]:
    """Pick a document's domain: ask the LLM first, fall back to keywords.

    Returns (domain, method), where method is "llm" or "keywords", so the
    caller can tell the user when the less accurate fallback was used.
    """
    domain = classify_domain_with_llm(text, filename)
    if domain:
        return domain, "llm"
    return detect_domain_by_keywords(text), "keywords"


def validate_domain(domain: str) -> bool:
    """Check if a domain string is valid."""
    return domain in DOMAIN_COLLECTIONS
