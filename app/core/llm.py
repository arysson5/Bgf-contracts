"""Cliente LLM OpenAI compartilhado."""

from langchain_openai import ChatOpenAI
from loguru import logger

from app.utils.settings import get_settings

# Modelo leve padrão (tarefas simples)
DEFAULT_MODEL = "gpt-4o-mini"
# Modelo robusto padrão (análises criteriosas)
DEFAULT_MODEL_PRO = "gpt-4o"

# Nomes antigos (Gemini) ou aliases → modelos OpenAI atuais
MODEL_ALIASES: dict[str, str] = {
    "gemini-1.5-flash": DEFAULT_MODEL,
    "gemini-1.5-flash-latest": DEFAULT_MODEL,
    "gemini-1.5-pro": DEFAULT_MODEL_PRO,
    "gemini-pro": DEFAULT_MODEL_PRO,
    "gemini-2.0-flash": DEFAULT_MODEL,
    "gemini-2.0-flash-lite": DEFAULT_MODEL,
    "gemini-2.5-flash": DEFAULT_MODEL,
    "gemini-2.5-flash-lite": DEFAULT_MODEL,
    "gemini-2.5-pro": DEFAULT_MODEL_PRO,
    "gpt-4o-mini-latest": DEFAULT_MODEL,
    "gpt-4o-latest": DEFAULT_MODEL_PRO,
}


def resolve_model_name(name: str) -> str:
    resolved = MODEL_ALIASES.get(name.strip(), name.strip())
    if resolved != name:
        logger.warning("Modelo '{}' mapeado para '{}'", name, resolved)
    return resolved


def get_llm_pro(
    temperature: float = 0,
    max_output_tokens: int | None = None,
) -> ChatOpenAI:
    """Modelo Pro (criteriosa) — usa MODEL_NAME_PRO ou fallback para MODEL_NAME."""
    return get_llm(temperature=temperature, max_output_tokens=max_output_tokens, use_pro=True)


def get_llm(
    temperature: float = 0,
    max_output_tokens: int | None = None,
    *,
    use_pro: bool = False,
) -> ChatOpenAI:
    from app.utils.windows_runtime import ensure_runtime_ok

    ensure_runtime_ok()
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError(
            "OPENAI_API_KEY não configurada. Copie .env.example para .env e defina sua chave."
        )
    if use_pro and settings.model_name_pro.strip():
        raw_name = settings.model_name_pro.strip()
    else:
        raw_name = settings.model_name
    model = resolve_model_name(raw_name)
    return ChatOpenAI(
        model=model,
        api_key=settings.openai_api_key,
        temperature=temperature,
        max_tokens=max_output_tokens or settings.max_tokens,
    )
