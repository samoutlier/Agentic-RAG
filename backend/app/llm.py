from langchain_groq import ChatGroq
from app.config import GROQ_API_KEY, LLM_MODEL, LLM_TEMPERATURE, CLASSIFIER_MODEL

# Fail at startup with setup instructions, rather than with a confusing
# authentication error on the first upload or question.
if not GROQ_API_KEY:
    raise RuntimeError(
        "GROQ_API_KEY is not set. Copy backend/.env.example to backend/.env "
        "and add your free API key from https://console.groq.com"
    )

# Answers questions in the chat.
chat_llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model_name=LLM_MODEL,
    temperature=LLM_TEMPERATURE,
)

# Classifies uploaded documents into a domain.
# - A smaller model is plenty for a one-word answer, and Groq applies rate
#   limits per model, so classifying uploads never eats into the chat
#   model's tokens-per-minute budget.
# - reasoning_effort="low" stops the model spending tokens thinking about
#   an easy decision.
# - No retries and a short timeout: if Groq is slow or unavailable, the
#   upload falls back to keyword matching instead of making the user wait.
classifier_llm = ChatGroq(
    api_key=GROQ_API_KEY,
    model_name=CLASSIFIER_MODEL,
    temperature=0,
    max_retries=0,
    timeout=15,
    model_kwargs={"reasoning_effort": "low"},
)
