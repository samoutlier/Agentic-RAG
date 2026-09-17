from langchain.prompts import PromptTemplate


def _build_template(domain_label: str, focus: str) -> str:
    """Build a prompt template string for a domain.

    Note the doubled braces: `{{history}}`, `{{context}}` and `{{question}}`
    become literal `{history}` / `{context}` / `{question}` in the output
    string — these stay as placeholders for LangChain's PromptTemplate to fill
    at query time. The single-brace {domain_label} and {focus} are filled now.
    """
    return f"""
You are an expert AI assistant for {domain_label} document analysis.
Use ONLY the provided context to answer the question. If the context
does not contain enough information, say so clearly — do not make up answers.

When referencing information, cite the source filename and page number.

Conversation so far:
{{history}}

Use the conversation only to understand what the question refers to
(for example "it", "that clause", or "the second one"). Every fact in your
answer must still come from the context below.

Context:
{{context}}

Question: {{question}}

Focus on:
{focus}

Answer:"""


PROMPT_VARIABLES = ["history", "context", "question"]

DOMAIN_PROMPTS = {
    "legal": PromptTemplate(
        input_variables=PROMPT_VARIABLES,
        template=_build_template("legal", """- Identifying specific clauses, obligations, and rights
- Highlighting potential risks or ambiguities
- Referencing relevant legal standards or regulations
- Using precise legal terminology"""),
    ),

    "finance": PromptTemplate(
        input_variables=PROMPT_VARIABLES,
        template=_build_template("financial", """- Quantitative data, figures, and trends
- Risk factors and their potential impact
- Regulatory compliance implications
- Comparing against standard financial benchmarks"""),
    ),

    "healthcare": PromptTemplate(
        input_variables=PROMPT_VARIABLES,
        template=_build_template("healthcare", """- Clinical findings, methodologies, and outcomes
- Patient safety considerations
- Statistical significance of results
- Relevant medical guidelines or standards"""),
    ),

    "enterprise": PromptTemplate(
        input_variables=PROMPT_VARIABLES,
        template=_build_template("enterprise", """- Clear actionable steps and procedures
- Roles, responsibilities, and escalation paths
- Alignment with organizational policies
- Practical implementation guidance"""),
    ),
}


def get_prompt(domain: str) -> PromptTemplate:
    """Return the prompt template for a given domain."""
    if domain not in DOMAIN_PROMPTS:
        raise ValueError(f"Unknown domain: {domain}. Valid: {list(DOMAIN_PROMPTS.keys())}")
    return DOMAIN_PROMPTS[domain]
