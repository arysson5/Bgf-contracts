"""Localização unificada de trechos em PDF e DOCX."""

from pathlib import Path

from loguru import logger

from app.core.docx_viewer import find_text_in_docx
from app.core.pdf_viewer import find_text_locations as find_in_pdf
from app.models.schemas import ContractualChange, TextLocation


def detect_file_type(file_path: str) -> str:
    return Path(file_path).suffix.lower().lstrip(".")


def find_in_document(file_path: str, query: str, max_results: int = 3) -> list[TextLocation]:
    if not query or not file_path:
        return []
    ft = detect_file_type(file_path)
    if ft == "pdf":
        locs = find_in_pdf(file_path, query, max_results)
        for loc in locs:
            loc.document_type = "pdf"
        return locs
    if ft in ("docx", "doc"):
        return find_text_in_docx(file_path, query, max_results)
    return []


def attach_locations_to_changes(
    changes: list[ContractualChange],
    path_base: str | None,
    path_new: str | None,
) -> list[ContractualChange]:
    """Mapeia cada alteração contratual para trechos nos documentos."""
    for ch in changes:
        if path_base and ch.original_text:
            ch.locations_base = find_in_document(path_base, ch.original_text[:300])
        if not ch.locations_base and path_base and ch.clause_reference:
            ch.locations_base = find_in_document(path_base, ch.clause_reference)

        if path_new and ch.new_text:
            ch.locations_new = find_in_document(path_new, ch.new_text[:300])
        if not ch.locations_new and path_new and ch.clause_reference:
            ch.locations_new = find_in_document(path_new, ch.clause_reference)

    logger.info("Localizações anexadas a {} alterações", len(changes))
    return changes
