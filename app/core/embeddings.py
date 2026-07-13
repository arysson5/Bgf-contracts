"""Embeddings Google Gemini — indexação leve de blocos de diff."""

from __future__ import annotations

import math
from functools import lru_cache

from langchain_google_genai import GoogleGenerativeAIEmbeddings
from loguru import logger

from app.utils.settings import get_settings

DEFAULT_EMBEDDING_MODEL = "models/text-embedding-004"


@lru_cache(maxsize=1)
def get_embeddings_client() -> GoogleGenerativeAIEmbeddings | None:
    settings = get_settings()
    if not settings.google_api_key:
        logger.warning("GOOGLE_API_KEY ausente — busca por embedding desativada")
        return None
    model = settings.embedding_model or DEFAULT_EMBEDDING_MODEL
    if not model.startswith("models/"):
        model = f"models/{model}"
    return GoogleGenerativeAIEmbeddings(
        model=model,
        google_api_key=settings.google_api_key,
    )


def embeddings_available() -> bool:
    return get_embeddings_client() is not None


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Gera embeddings em lote (documentos). Retorna lista vazia se API indisponível."""
    if not texts:
        return []
    client = get_embeddings_client()
    if client is None:
        return []
    cleaned = [(t or " ").strip()[:8000] or " " for t in texts]
    try:
        return client.embed_documents(cleaned)
    except Exception as exc:
        logger.error("Falha ao gerar embeddings: {}", exc)
        return []


def embed_query(text: str) -> list[float]:
    client = get_embeddings_client()
    if client is None:
        return []
    try:
        return client.embed_query((text or " ").strip()[:8000])
    except Exception as exc:
        logger.error("Falha ao gerar embedding de consulta: {}", exc)
        return []


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)
