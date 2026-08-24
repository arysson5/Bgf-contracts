"""Validação e gravação segura de comentários no arquivo de trabalho."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx"}


class AnnotationError(ValueError):
    """Erro recuperável ao gravar comentário (arquivo travado, texto vazio, etc.)."""


def validate_comment_text(comment_text: str) -> str:
    text = (comment_text or "").strip()
    if not text:
        raise AnnotationError("Escreva o texto do comentário antes de gravar.")
    if len(text) > 8000:
        raise AnnotationError("O comentário é longo demais (máximo de 8.000 caracteres).")
    return text


def validate_document_path(file_path: str | Path, *, must_exist: bool = True) -> Path:
    path = Path(file_path)
    suffix = path.suffix.lower()
    if suffix == ".doc":
        raise AnnotationError(
            "Arquivo .doc não é suportado para comentários. "
            "Abra no Word e salve como .docx."
        )
    if suffix not in SUPPORTED_SUFFIXES:
        raise AnnotationError(
            f"Formato {suffix or '(sem extensão)'} não suportado. Use PDF ou DOCX."
        )
    if must_exist and not path.is_file():
        raise AnnotationError(f"Arquivo não encontrado: {path.name}")
    return path.resolve()


def assert_writable(path: Path) -> None:
    """Falha cedo se o arquivo estiver aberto no Word/Adobe ou for somente leitura."""
    path = validate_document_path(path)
    if not os.access(path, os.W_OK):
        raise AnnotationError(
            f"Sem permissão para gravar em «{path.name}». "
            "Verifique se o arquivo não está marcado como somente leitura."
        )
    try:
        with open(path, "rb+"):
            pass
    except OSError:
        raise AnnotationError(
            f"Não foi possível gravar em «{path.name}». "
            "Feche o arquivo no Word, Adobe Acrobat ou outro programa e tente de novo."
        ) from None


def make_sibling_temp(dest: Path) -> Path:
    fd, name = tempfile.mkstemp(
        prefix=f"{dest.stem}_",
        suffix=dest.suffix,
        dir=str(dest.parent),
    )
    os.close(fd)
    return Path(name)


def atomic_replace(tmp_path: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.replace(str(tmp_path), str(dest))
