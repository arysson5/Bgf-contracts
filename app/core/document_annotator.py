"""Inserção de comentários em PDF ou DOCX (grava no próprio arquivo)."""

from app.core.annotation_io import validate_comment_text, validate_document_path
from app.core.docx_viewer import add_comment_to_docx
from app.core.pdf_viewer import add_comment_to_pdf
from app.models.schemas import PdfRect, TextLocation


def add_comment_to_document(
    file_path: str,
    comment_text: str,
    anchor_text: str | None = None,
    locations: list[TextLocation] | None = None,
    output_path: str | None = None,
    *,
    percent_point: tuple[float, float] | None = None,
    percent_rect: tuple[float, float, float, float] | None = None,
    paragraph_index: int | None = None,
    page_num: int | None = None,
) -> str:
    """Grava o comentário no arquivo (in-place, salvo se output_path for informado)."""
    comment_text = validate_comment_text(comment_text)
    src = validate_document_path(file_path)
    dest = output_path or str(src)
    loc = locations[0] if locations else None
    ft = src.suffix.lower()

    if ft == ".pdf":
        page = page_num or (loc.page if loc else 1)
        rects: list[PdfRect] = list(loc.rects) if loc and loc.rects else []
        return add_comment_to_pdf(
            str(src),
            page,
            comment_text,
            anchor_text=anchor_text,
            output_path=dest,
            rects=rects or None,
            percent_point=percent_point,
            percent_rect=percent_rect,
        )

    if ft in (".docx", ".doc"):
        para_idx = paragraph_index
        if para_idx is None and loc is not None:
            if loc.paragraph_index is not None:
                para_idx = loc.paragraph_index
            elif loc.document_type == "docx":
                para_idx = max(0, (loc.page or 1) - 1)
        if para_idx is None:
            para_idx = 0
        return add_comment_to_docx(str(src), para_idx, comment_text, output_path=dest)

    raise ValueError("Formato não suportado para anotações.")
