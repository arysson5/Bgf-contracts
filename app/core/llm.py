"""Cliente LLM Google Gemini compartilhado."""

from langchain_google_genai import ChatGoogleGenerativeAI
from loguru import logger

from app.utils.settings import get_settings

# Nomes antigos/inválidos → modelo atual suportado pela API
# Modelos descontinuados/indisponíveis → padrão atual para contas novas
DEFAULT_MODEL = "gemini-2.5-flash"

MODEL_ALIASES: dict[str, str] = {
    "gemini-1.5-flash": DEFAULT_MODEL,
    "gemini-1.5-flash-latest": DEFAULT_MODEL,
    "gemini-1.5-pro": DEFAULT_MODEL,
    "gemini-pro": DEFAULT_MODEL,
    "gemini-2.0-flash": DEFAULT_MODEL,
    "gemini-2.0-flash-lite": "gemini-2.5-flash-lite",
}


def resolve_model_name(name: str) -> str:
    resolved = MODEL_ALIASES.get(name.strip(), name.strip())
    if resolved != name:
        logger.warning("Modelo '{}' mapeado para '{}'", name, resolved)
    return resolved


def get_llm_pro(
    temperature: float = 0,
    max_output_tokens: int | None = None,
) -> ChatGoogleGenerativeAI:
    """Modelo Pro (criteriosa) — usa MODEL_NAME_PRO ou fallback para MODEL_NAME."""
    return get_llm(temperature=temperature, max_output_tokens=max_output_tokens, use_pro=True)


def get_llm(
    temperature: float = 0,
    max_output_tokens: int | None = None,
    *,
    use_pro: bool = False,
) -> ChatGoogleGenerativeAI:
    from app.utils.windows_runtime import ensure_runtime_ok

    ensure_runtime_ok()
    settings = get_settings()
    if not settings.google_api_key:
        raise ValueError(
            "GOOGLE_API_KEY não configurada. Copie .env.example para .env e defina sua chave."
        )
    if use_pro and settings.model_name_pro.strip():
        raw_name = settings.model_name_pro.strip()
    else:
        raw_name = settings.model_name
    model = resolve_model_name(raw_name)
    return ChatGoogleGenerativeAI(
        model=model,
        google_api_key=settings.google_api_key,
        temperature=temperature,
        max_output_tokens=max_output_tokens or settings.max_tokens,
    )
