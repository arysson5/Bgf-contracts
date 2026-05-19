"""Inserção de comentários em PDF ou DOCX."""

from pathlib import Path

from app.core.docx_viewer import add_comment_to_docx
from app.core.pdf_viewer import add_comment_to_pdf
from app.models.schemas import TextLocation


def add_comment_to_document(
    file_path: str,
    comment_text: str,
    anchor_text: str | None = None,
    locations: list[TextLocation] | None = None,
    output_path: str | None = None,
) -> str:
    ft = Path(file_path).suffix.lower()
    page_or_para = 1
    if locations:
        loc = locations[0]
        page_or_para = (loc.paragraph_index if loc.paragraph_index is not None else loc.page - 1) + (
            0 if loc.paragraph_index is not None else 0
        )
        if loc.document_type == "docx" and loc.paragraph_index is not None:
            page_or_para = loc.paragraph_index
        else:
            page_or_para = loc.page

    if ft == ".pdf":
        return add_comment_to_pdf(
            file_path, page_or_para, comment_text, anchor_text=anchor_text, output_path=output_path
        )
    if ft in (".docx", ".doc"):
        para_idx = page_or_para - 1 if locations and locations[0].document_type != "docx" else page_or_para
        if locations and locations[0].paragraph_index is not None:
            para_idx = locations[0].paragraph_index
        return add_comment_to_docx(file_path, para_idx, comment_text, output_path=output_path)
    raise ValueError("Formato não suportado para anotações.")
