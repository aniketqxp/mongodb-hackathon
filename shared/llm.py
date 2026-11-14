"""get_llm(): one place to pick the LLM provider. Switch with env vars only."""
import os


def get_llm(temperature: float = 0.0):
    provider = os.getenv("LLM_PROVIDER", "groq").lower()
    model = os.getenv("LLM_MODEL", "openai/gpt-oss-120b")
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(model=model, temperature=temperature, api_key=os.environ["GROQ_API_KEY"])
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=model,
            temperature=temperature,
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url="https://openrouter.ai/api/v1",
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {provider!r} (use 'groq' or 'openrouter')")


def structured(schema):
    """LLM bound to a JSON schema. Strict output works on Groq gpt-oss models."""
    llm = get_llm()
    if os.getenv("LLM_PROVIDER", "groq").lower() == "groq":
        return llm.with_structured_output(schema, method="json_schema")
    return llm.with_structured_output(schema)
