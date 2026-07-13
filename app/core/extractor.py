"""Extração de texto de PDF e DOCX e comentários de PDF."""

import hashlib
import re
import uuid
from pathlib import Path

import fitz  # pymupdf
import mammoth
import pdfplumber
from docx import Document as DocxDocument
from loguru import logger

from app.models.schemas import DocumentType


def compute_comment_stable_id(
    file_path: str,
    *,
    page: int | str = "",
    author: str = "",
    comment_text: str = "",
    referenced_text: str = "",
    date_str: str = "",
    paragraph_index: int | None = None,
) -> str:
    """ID estável para vincular comentários entre versões e análises."""
    name = Path(file_path).name
    blob = "|".join([
        name,
        str(page),
        str(paragraph_index or ""),
        author.strip(),
        comment_text.strip()[:500],
        referenced_text.strip()[:200],
        date_str.strip(),
    ])
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


stable_comment_id = compute_comment_stable_id


def normalize_text(text: str) -> str:
    """Remove espaços/quebras excessivas e caracteres de controle."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Remove linhas típicas de cabeçalho/rodapé de página (números isolados)
    lines = []
    for line in text.split("\n"):
        stripped = line.strip()
        if re.fullmatch(r"\d{1,4}", stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _detect_type(file_path: str) -> DocumentType:
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return DocumentType.PDF
    if suffix in (".docx", ".doc"):
        return DocumentType.DOCX
    raise ValueError(f"Formato não suportado: {suffix}. Use PDF ou DOCX.")


def _extract_docx(file_path: str) -> str:
    with open(file_path, "rb") as f:
        result = mammoth.extract_raw_text(f)
    text = (result.value or "").strip()
    if len(text) < 100:
        logger.warning("Mammoth retornou pouco texto; tentando python-docx.")
        doc = DocxDocument(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        text = "\n".join(paragraphs)
    return normalize_text(text)


def _extract_pdf_pdfplumber(file_path: str) -> str:
    parts: list[str] = []
    with pdfplumber.open(file_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                parts.append(page_text)
    return normalize_text("\n".join(parts))


def _extract_pdf_pymupdf(file_path: str) -> str:
    doc = fitz.open(file_path)
    parts: list[str] = []
    try:
        for page in doc:
            parts.append(page.get_text("text"))
    finally:
        doc.close()
    return normalize_text("\n".join(parts))


def _extract_pdf(file_path: str) -> str:
    text = _extract_pdf_pdfplumber(file_path)
    if len(text) < 100:
        logger.warning("pdfplumber retornou pouco texto; tentando pymupdf.")
        text = _extract_pdf_pymupdf(file_path)
    return text


def extract_text(file_path: str) -> tuple[str, DocumentType]:
    """
    Recebe caminho do arquivo.
    Retorna (texto_extraído_normalizado, tipo_documento).
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")

    doc_type = _detect_type(file_path)
    logger.info("Extraindo texto de {} ({})", path.name, doc_type.value)

    try:
        if doc_type == DocumentType.DOCX:
            text = _extract_docx(file_path)
        else:
            text = _extract_pdf(file_path)
    except Exception as exc:
        logger.exception("Falha ao extrair texto de {}", path.name)
        raise ValueError(
            f"Não foi possível extrair texto do arquivo. "
            f"O PDF pode estar escaneado sem OCR ou o arquivo está corrompido. Detalhe: {exc}"
        ) from exc

    if len(text) < 50:
        raise ValueError(
            "Texto extraído insuficiente (< 50 caracteres). "
            "Verifique se o PDF não é apenas imagem escaneada sem camada de texto."
        )

    logger.info("Extraídos {} caracteres de {}", len(text), path.name)
    return text, doc_type


# Tipos de anotação que costumam carregar revisão/comentário (Acrobat, Bluebeam, etc.)
_COMMENT_ANNOT_NAMES = frozenset({
    "Text",
    "FreeText",
    "Highlight",
    "Underline",
    "Squiggly",
    "StrikeOut",
    "Caret",
    "Ink",
    "Polygon",
    "PolyLine",
})
# Popup repete o texto do pai; ignorar para não duplicar
_SKIP_ANNOT_NAMES = frozenset({
    "Popup",
    "Link",
    "Widget",
    "FileAttachment",
    "Sound",
    "Movie",
    "Screen",
    "PrinterMark",
    "TrapNet",
    "Watermark",
    "3D",
})


def _annot_type_name(annot) -> str:
    if annot.type and len(annot.type) > 1:
        return annot.type[1] or ""
    return ""


def _comment_text_from_annot(annot) -> str:
    info = annot.info or {}
    parts = [
        info.get("content"),
        info.get("subject"),
        annot.get_text(),
    ]
    for raw in parts:
        if not raw:
            continue
        text = str(raw).strip()
        if text:
            return text
    return ""


def _referenced_text_from_annot(page, annot, comment_text: str) -> str:
    """Trecho do documento ancorado à anotação (retângulo do highlight/nota)."""
    try:
        rect = annot.rect
        if rect and not rect.is_empty:
            excerpt = page.get_text("text", clip=rect).strip()
            if excerpt:
                return excerpt[:2000]
    except Exception:
        pass

    # Fallback: busca por trecho citado no próprio comentário
    needle = comment_text.replace("Por favor, ajustar para:", "").strip()
    for search in (needle[:120], needle[:80], comment_text[:80]):
        if len(search) < 8:
            continue
        try:
            rects = page.search_for(search)
            if rects:
                return page.get_text("text", clip=rects[0]).strip()[:2000]
        except Exception:
            continue
    return ""


def _is_review_annotation(annot) -> bool:
    type_name = _annot_type_name(annot)
    if type_name in _SKIP_ANNOT_NAMES:
        return False
    if type_name in _COMMENT_ANNOT_NAMES:
        return True
    # Tipos numéricos PyMuPDF: 0 Text, 2 FreeText, 8 Highlight, 9-11 markup
    atype = annot.type[0] if annot.type else None
    return atype in (0, 2, 8, 9, 10, 11, 13, 15)


def extract_comments_from_pdf(file_path: str) -> list[dict]:
    """
    Extrai comentários de revisão do PDF via PyMuPDF.

    Inclui notas (Text), caixas (FreeText) e **destaques** (Highlight) —
    formato mais comum em PDFs revisados no Acrobat.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Extração de comentários suportada apenas para PDF.")

    comments: list[dict] = []
    seen: set[tuple[int, str]] = set()
    doc = fitz.open(file_path)
    try:
        for page_index, page in enumerate(doc):
            for annot in page.annots() or []:
                if annot is None or not _is_review_annotation(annot):
                    continue

                comment_text = _comment_text_from_annot(annot)
                if not comment_text:
                    continue

                rect = annot.rect
                dedup_key = (
                    page_index + 1,
                    round(rect.x0, 1),
                    round(rect.y0, 1),
                    round(rect.x1, 1),
                    round(rect.y1, 1),
                    comment_text[:120],
                )
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)

                info = annot.info or {}
                referenced = _referenced_text_from_annot(page, annot, comment_text)
                type_name = _annot_type_name(annot)

                author = info.get("title") or info.get("author") or "Desconhecido"
                page_num = page_index + 1
                stable_id = compute_comment_stable_id(
                    file_path,
                    page=page_num,
                    author=author,
                    comment_text=comment_text,
                    referenced_text=referenced,
                    date_str=info.get("modDate") or info.get("creationDate") or "",
                )
                comments.append(
                    {
                        "id": stable_id,
                        "stable_id": stable_id,
                        "page": page_num,
                        "comment_text": comment_text,
                        "referenced_text": referenced,
                        "author": author,
                        "date": info.get("modDate") or info.get("creationDate") or "",
                        "annot_type": type_name,
                        "rects": [
                            {
                                "x0": round(rect.x0, 2),
                                "y0": round(rect.y0, 2),
                                "x1": round(rect.x1, 2),
                                "y1": round(rect.y1, 2),
                            }
                        ],
                    }
                )
    finally:
        doc.close()

    logger.info("Extraídos {} comentários de {}", len(comments), path.name)
    return comments


def extract_comments(file_path: str) -> list[dict]:
    """Extrai comentários de PDF ou DOCX."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return extract_comments_from_pdf(file_path)
    if suffix in (".docx", ".doc"):
        from app.core.docx_viewer import extract_comments_from_docx

        return extract_comments_from_docx(file_path)
    raise ValueError("Extração de comentários suportada apenas para PDF e DOCX.")
