"""Extração de texto de PDF e DOCX e comentários de PDF."""

import re
import uuid
from pathlib import Path

import fitz  # pymupdf
import mammoth
import pdfplumber
from docx import Document as DocxDocument
from loguru import logger

from app.models.schemas import DocumentType


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


def extract_comments_from_pdf(file_path: str) -> list[dict]:
    """
    Extrai anotações Text e FreeText do PDF via pymupdf.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {file_path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError("Extração de comentários suportada apenas para PDF.")

    comments: list[dict] = []
    doc = fitz.open(file_path)
    try:
        for page_index, page in enumerate(doc):
            for annot in page.annots() or []:
                if annot is None:
                    continue
                atype = annot.type[0] if annot.type else None
                # 0=Text, 2=FreeText (varia por versão; incluir nomes comuns)
                type_name = annot.type[1] if annot.type and len(annot.type) > 1 else ""
                if atype not in (0, 2) and type_name not in ("Text", "FreeText"):
                    continue

                info = annot.info or {}
                comment_text = (info.get("content") or annot.get_text() or "").strip()
                if not comment_text:
                    continue

                referenced = ""
                try:
                    quad = annot.vertices
                    if quad:
                        rects = page.search_for(comment_text[:80]) if len(comment_text) > 3 else []
                        if rects:
                            referenced = page.get_text("text", clip=rects[0]).strip()
                except Exception:
                    pass

                if not referenced:
                    try:
                        rect = annot.rect
                        referenced = page.get_text("text", clip=rect).strip()
                    except Exception:
                        referenced = ""

                comments.append(
                    {
                        "id": str(uuid.uuid4()),
                        "page": page_index + 1,
                        "comment_text": comment_text,
                        "referenced_text": referenced[:2000] if referenced else "",
                        "author": info.get("title") or info.get("author") or "Desconhecido",
                        "date": info.get("modDate") or info.get("creationDate") or "",
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
