"""Funções auxiliares — tokens, chunking, JSON."""

import json
import re

from loguru import logger

from app.utils.datetime_br import (  # reexport
    BRAZIL_TZ,
    brazil_today,
    format_brazil_datetime,
    to_brazil_time,
)

_tiktoken_encoding = None
_text_splitter = None


def _get_encoding(encoding_name: str = "cl100k_base"):
    global _tiktoken_encoding
    if _tiktoken_encoding is None:
        import tiktoken

        _tiktoken_encoding = tiktoken.get_encoding(encoding_name)
    return _tiktoken_encoding


def count_tokens(text: str, encoding_name: str = "cl100k_base") -> int:
    enc = _get_encoding(encoding_name)
    return len(enc.encode(text))


def chunk_text(text: str, chunk_size: int = 4000, overlap: int = 200) -> list[str]:
    global _text_splitter
    if _text_splitter is None:
        from langchain_text_splitters import RecursiveCharacterTextSplitter

        _text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=overlap,
            length_function=count_tokens,
        )
    chunks = _text_splitter.split_text(text)
    logger.debug("Texto dividido em {} chunks", len(chunks))
    return chunks


def format_requirements_for_prompt(requirements: list[dict]) -> str:
    lines = []
    for req in requirements:
        critical = " [OBRIGATÓRIO]" if req.get("is_critical") else ""
        lines.append(f"- id={req['id']}: {req['text']}{critical}")
    return "\n".join(lines)


def safe_json_parse(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.error("JSON inválido: {}", exc)
        raise ValueError(f"Resposta da IA não é JSON válido: {exc}") from exc
