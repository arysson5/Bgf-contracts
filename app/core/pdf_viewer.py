"""Visualização e anotação de PDF — localizar trechos e destacar alterações."""

import re
import uuid
from pathlib import Path

import fitz
from loguru import logger
from rapidfuzz import fuzz

from app.models.schemas import DiffLocation, DiffType, PdfRect, TextLocation

# Cores RGB (0-1) para highlights
COLOR_ADDED = (0.2, 0.85, 0.4)
COLOR_REMOVED = (1.0, 0.35, 0.35)
COLOR_HIGHLIGHT = (1.0, 0.95, 0.2)
COLOR_COMMENT = (0.3, 0.5, 1.0)


def _clean_query(text: str, max_len: int = 120) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) > max_len:
        t = t[:max_len]
    return t


def _rect_to_model(r: fitz.Rect) -> PdfRect:
    return PdfRect(x0=r.x0, y0=r.y0, x1=r.x1, y1=r.y1)


def _model_to_rect(r: PdfRect) -> fitz.Rect:
    return fitz.Rect(r.x0, r.y0, r.x1, r.y1)


def find_text_locations(
    pdf_path: str,
    query: str,
    max_results: int = 5,
) -> list[TextLocation]:
    """Localiza trecho no PDF (busca exata e fuzzy por página)."""
    query = _clean_query(query)
    if len(query) < 4:
        return []

    path = Path(pdf_path)
    if not path.exists() or path.suffix.lower() != ".pdf":
        return []

    locations: list[TextLocation] = []
    doc = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(doc):
            page_num = page_index + 1
            # Busca exata (fragmentos se texto longo)
            search_terms = [query]
            if len(query) > 60:
                search_terms = [query[:60], query[:40], query[-60:]]

            for term in search_terms:
                if len(term) < 4:
                    continue
                rects = page.search_for(term)
                if rects:
                    for rect in rects[:max_results]:
                        excerpt = page.get_text("text", clip=rect).strip()[:300]
                        locations.append(
                            TextLocation(
                                page=page_num,
                                text=excerpt or term,
                                rects=[_rect_to_model(rect)],
                                match_score=1.0,
                            )
                        )
                    if locations:
                        break

            if locations:
                continue

            # Fuzzy: compara query com blocos de texto da página
            page_text = page.get_text("text")
            if not page_text or len(page_text) < 10:
                continue
            blocks = [b.strip() for b in page_text.split("\n") if len(b.strip()) > 15]
            best_score = 0
            best_block = ""
            for block in blocks:
                score = fuzz.partial_ratio(query, block)
                if score > best_score:
                    best_score = score
                    best_block = block
            if best_score >= 75 and best_block:
                rects = page.search_for(best_block[:80])
                if rects:
                    locations.append(
                        TextLocation(
                            page=page_num,
                            text=best_block[:300],
                            rects=[_rect_to_model(rects[0])],
                            match_score=best_score / 100.0,
                        )
                    )
    finally:
        doc.close()

    return locations[:max_results]


def map_diff_to_pdf(
    pdf_path_base: str,
    pdf_path_new: str,
    diff_blocks: list,
) -> list[DiffLocation]:
    """Mapeia blocos de diff para páginas nos PDFs base e novo."""
    locations: list[DiffLocation] = []
    for block in diff_blocks:
        if block.block_type == DiffType.UNCHANGED:
            continue
        text = _clean_query(block.text)
        if len(text) < 5:
            continue

        change_id = str(uuid.uuid4())[:8]
        if block.block_type == DiffType.ADDED:
            locs = find_text_locations(pdf_path_new, text)
            source = "new"
        else:
            locs = find_text_locations(pdf_path_base, text)
            source = "base"

        locations.append(
            DiffLocation(
                change_id=change_id,
                block_type=block.block_type,
                text=block.text[:500],
                locations=locs,
                source_version=source,
            )
        )
    logger.info("Mapeadas {} alterações para o PDF", len(locations))
    return locations


def render_page_image(
    pdf_path: str,
    page_num: int,
    highlight_rects: list[PdfRect] | None = None,
    highlight_color: tuple[float, float, float] = COLOR_HIGHLIGHT,
    zoom: float = 1.5,
) -> bytes:
    """Renderiza página do PDF como PNG com retângulos destacados."""
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_num - 1]
        if highlight_rects:
            for pr in highlight_rects:
                rect = _model_to_rect(pr)
                highlight = page.add_highlight_annot(rect)
                highlight.set_colors(stroke=highlight_color)
                highlight.update()
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def build_highlighted_pdf(
    pdf_path: str,
    locations: list[TextLocation],
    color: tuple[float, float, float] = COLOR_HIGHLIGHT,
    output_path: str | None = None,
) -> str:
    """Gera cópia do PDF com highlights nas posições indicadas."""
    src = Path(pdf_path)
    if output_path:
        dest = Path(output_path)
    else:
        dest = src.parent / f"{src.stem}_destacado.pdf"

    doc = fitz.open(pdf_path)
    try:
        for loc in locations:
            if not loc.rects:
                continue
            page = doc[loc.page - 1]
            for pr in loc.rects:
                annot = page.add_highlight_annot(_model_to_rect(pr))
                annot.set_colors(stroke=color)
                annot.update()
        doc.save(str(dest), garbage=4, deflate=True)
    finally:
        doc.close()
    return str(dest)


def add_comment_to_pdf(
    pdf_path: str,
    page_num: int,
    comment_text: str,
    anchor_text: str | None = None,
    output_path: str | None = None,
) -> str:
    """Insere comentário (anotação Text) no PDF."""
    src = Path(pdf_path)
    if output_path:
        dest = Path(output_path)
    else:
        dest = src.parent / f"{src.stem}_com_comentarios.pdf"

    # Copiar para não sobrescrever original
    if dest.resolve() != src.resolve():
        import shutil

        shutil.copy2(src, dest)
        work_path = str(dest)
    else:
        work_path = str(src)

    doc = fitz.open(work_path)
    try:
        page = doc[page_num - 1]
        point = fitz.Point(72, 72)
        if anchor_text:
            rects = page.search_for(_clean_query(anchor_text, 80))
            if rects:
                point = rects[0].top_left

        annot = page.add_text_annot(point, comment_text)
        annot.set_info(content=comment_text, title="BGF Revisão")
        annot.set_colors(stroke=COLOR_COMMENT)
        annot.update()
        # PyMuPDF exige salvamento incremental ao gravar no mesmo arquivo aberto
        if Path(work_path).resolve() == Path(dest).resolve():
            doc.saveIncr()
        else:
            doc.save(str(dest), garbage=4, deflate=True)
    finally:
        doc.close()

    logger.info("Comentário adicionado na página {} → {}", page_num, dest.name)
    return str(dest)


def get_pdf_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()
