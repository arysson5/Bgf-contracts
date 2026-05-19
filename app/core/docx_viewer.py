"""Navegação e anotação em documentos DOCX."""

import html
import re
import uuid
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt
from loguru import logger
from rapidfuzz import fuzz

from app.models.schemas import TextLocation


def find_text_in_docx(file_path: str, query: str, max_results: int = 5) -> list[TextLocation]:
    """Localiza trecho nos parágrafos do DOCX."""
    query = re.sub(r"\s+", " ", (query or "").strip())
    if len(query) < 4:
        return []

    path = Path(file_path)
    if not path.exists() or path.suffix.lower() not in (".docx", ".doc"):
        return []

    doc = Document(file_path)
    locations: list[TextLocation] = []

    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        score = 100 if query in text else fuzz.partial_ratio(query, text)
        if score >= 75:
            locations.append(
                TextLocation(
                    page=idx + 1,
                    paragraph_index=idx,
                    text=text[:500],
                    match_score=score / 100.0,
                    document_type="docx",
                )
            )
            if len(locations) >= max_results:
                break

    return locations


def render_docx_paragraphs_html(
    file_path: str,
    highlight_indices: set[int] | None = None,
    highlight_color: str = "#fff3cd",
) -> str:
    """Renderiza parágrafos do DOCX como HTML com destaques."""
    doc = Document(file_path)
    parts = [
        "<style>.docx-view{font-family:Georgia,serif;line-height:1.7;padding:16px;"
        "background:#fafafa;border-radius:8px;max-height:70vh;overflow-y:auto}"
        ".docx-p{margin:8px 0;padding:8px;border-radius:4px}"
        ".docx-hl{background:" + highlight_color + ";border-left:4px solid #f59e0b}"
        ".docx-num{color:#6b7280;font-size:12px}</style><div class='docx-view'>",
    ]
    highlight_indices = highlight_indices or set()
    for idx, para in enumerate(doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        safe = html.escape(text)
        cls = "docx-p docx-hl" if idx in highlight_indices else "docx-p"
        parts.append(f'<p class="{cls}"><span class="docx-num">¶{idx+1}</span> {safe}</p>')
    parts.append("</div>")
    return "".join(parts)


def add_comment_to_docx(
    file_path: str,
    paragraph_index: int,
    comment_text: str,
    output_path: str | None = None,
) -> str:
    """Insere nota de revisão após o parágrafo referenciado."""
    import shutil

    src = Path(file_path)
    dest = Path(output_path) if output_path else src.parent / f"{src.stem}_comentarios.docx"
    if dest.resolve() != src.resolve():
        shutil.copy2(src, dest)

    doc = Document(str(dest))
    idx = min(max(0, paragraph_index), len(doc.paragraphs) - 1)
    if idx + 1 < len(doc.paragraphs):
        new_para = doc.paragraphs[idx + 1].insert_paragraph_before("")
    else:
        new_para = doc.add_paragraph()
    run = new_para.add_run(f"[Contract Analyzer] {comment_text}")
    run.bold = True
    run.font.size = Pt(10)
    run.font.highlight_color = WD_COLOR_INDEX.YELLOW

    doc.save(str(dest))
    logger.info("Comentário DOCX inserido após parágrafo {}", idx)
    return str(dest)


def extract_comments_from_docx(file_path: str) -> list[dict]:
    """Extrai comentários nativos do DOCX (quando existirem no XML)."""
    comments: list[dict] = []
    try:
        doc = Document(file_path)
        if hasattr(doc, "comments") and doc.comments:
            for i, cmt in enumerate(doc.comments):
                comments.append(
                    {
                        "id": str(uuid.uuid4()),
                        "page": 1,
                        "comment_text": getattr(cmt, "text", str(cmt)) or "",
                        "referenced_text": "",
                        "author": getattr(cmt, "author", "Desconhecido") or "Desconhecido",
                        "date": "",
                        "paragraph_index": i,
                    }
                )
    except Exception as exc:
        logger.debug("Comentários DOCX não disponíveis: {}", exc)
    return comments
