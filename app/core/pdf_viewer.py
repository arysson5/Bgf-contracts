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


def page_point_from_percent(page, x_pct: float, y_pct: float) -> fitz.Point:
    """Converte clique em % da imagem da página para ponto PDF."""
    x = max(0.0, min(100.0, float(x_pct))) / 100.0 * page.rect.width
    y = max(0.0, min(100.0, float(y_pct))) / 100.0 * page.rect.height
    return fitz.Point(x, y)


def rect_from_percent(
    page,
    x0_pct: float,
    y0_pct: float,
    x1_pct: float,
    y1_pct: float,
) -> fitz.Rect:
    x0, x1 = sorted((float(x0_pct), float(x1_pct)))
    y0, y1 = sorted((float(y0_pct), float(y1_pct)))
    r = page.rect
    return fitz.Rect(
        max(0.0, x0 / 100.0 * r.width),
        max(0.0, y0 / 100.0 * r.height),
        min(r.width, x1 / 100.0 * r.width),
        min(r.height, y1 / 100.0 * r.height),
    )


def text_near_pdf_point(
    pdf_path: str,
    page_num: int,
    x_pct: float,
    y_pct: float,
    radius: float = 36.0,
) -> str:
    """Trecho próximo ao clique (âncora sugerida no diálogo)."""
    path = Path(pdf_path)
    if not path.is_file() or path.suffix.lower() != ".pdf":
        return ""
    doc = fitz.open(str(path))
    try:
        if page_num < 1 or page_num > len(doc):
            return ""
        page = doc[page_num - 1]
        pt = page_point_from_percent(page, x_pct, y_pct)
        clip = fitz.Rect(
            max(0, pt.x - radius),
            max(0, pt.y - radius),
            min(page.rect.width, pt.x + radius * 3),
            min(page.rect.height, pt.y + radius),
        )
        return (page.get_text("text", clip=clip) or "").strip()[:500]
    finally:
        doc.close()


def _pdf_search_rects(page, anchor_text: str | None) -> list[fitz.Rect]:
    if not anchor_text:
        return []
    query = _clean_query(anchor_text, 80)
    if len(query) < 4:
        return []
    found = page.search_for(query)
    return list(found[:8]) if found else []


def _save_pdf_document(doc, dest: Path, *, incremental: bool) -> bool:
    """Grava o PDF. Retorna True se o documento já foi fechado."""
    from app.core.annotation_io import atomic_replace, make_sibling_temp

    if incremental:
        try:
            doc.saveIncr()
            return False
        except Exception as exc:
            logger.warning("saveIncr falhou em {}: {}", dest.name, exc)
    tmp = make_sibling_temp(dest)
    try:
        doc.save(str(tmp), garbage=4, deflate=True)
        doc.close()
        atomic_replace(tmp, dest)
        return True
    except Exception:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
        raise


def add_comment_to_pdf(
    pdf_path: str,
    page_num: int,
    comment_text: str,
    anchor_text: str | None = None,
    output_path: str | None = None,
    rects: list[PdfRect] | None = None,
    point: tuple[float, float] | None = None,
    percent_point: tuple[float, float] | None = None,
    percent_rect: tuple[float, float, float, float] | None = None,
) -> str:
    """Insere comentário nativo no PDF (Highlight no trecho ou nota no ponto)."""
    from app.core.annotation_io import (
        AnnotationError,
        assert_writable,
        validate_comment_text,
        validate_document_path,
    )

    comment_text = validate_comment_text(comment_text)
    src = validate_document_path(pdf_path)
    dest = Path(output_path).resolve() if output_path else src
    if dest.suffix.lower() != ".pdf":
        dest = dest.with_suffix(".pdf")

    if dest != src:
        import shutil

        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    assert_writable(dest)

    work_path = str(dest)
    doc = fitz.open(work_path)
    closed = False
    try:
        if page_num < 1 or page_num > len(doc):
            raise AnnotationError(
                f"Página {page_num} inválida — o PDF tem {len(doc)} página(s)."
            )
        page = doc[page_num - 1]
        target_rects: list[fitz.Rect] = []
        if percent_rect:
            sel = rect_from_percent(page, *percent_rect)
            if sel.width >= 4 and sel.height >= 4:
                target_rects.append(sel)
        if rects:
            target_rects.extend(_model_to_rect(r) for r in rects)
        if not target_rects:
            target_rects.extend(_pdf_search_rects(page, anchor_text))

        if target_rects:
            annot = page.add_highlight_annot(target_rects[0])
            annot.set_info(content=comment_text, title="BGF Revisão")
            annot.set_colors(stroke=COLOR_COMMENT)
            annot.update()
        else:
            if percent_point:
                pt = page_point_from_percent(page, percent_point[0], percent_point[1])
            elif point:
                pt = fitz.Point(float(point[0]), float(point[1]))
            else:
                raise AnnotationError(
                    "Não foi possível localizar o trecho no PDF. "
                    "Clique com o botão direito no ponto desejado no documento da direita."
                )
            annot = page.add_text_annot(pt, comment_text)
            annot.set_info(content=comment_text, title="BGF Revisão")
            annot.set_colors(stroke=COLOR_COMMENT)
            annot.update()

        incremental = Path(work_path).resolve() == dest.resolve()
        closed = _save_pdf_document(doc, dest, incremental=incremental)
    finally:
        if not closed:
            doc.close()

    logger.info("Comentário adicionado na página {} → {}", page_num, dest.name)
    return str(dest)


def get_pdf_page_count(pdf_path: str) -> int:
    doc = fitz.open(pdf_path)
    try:
        return len(doc)
    finally:
        doc.close()
