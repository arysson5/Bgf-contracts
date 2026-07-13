"""Comparação entre versões — diff textual e análise contratual por modo."""

from __future__ import annotations

from collections.abc import Callable

from loguru import logger

from app.core.contract_comparator import compare_contracts, compare_contracts_full_document
from app.core.document_locator import attach_locations_to_changes
from app.core.text_diff import compute_text_diff
from app.models.schemas import AnalysisMode, ContractDiffResult, TextDiffResult

ProgressCallback = Callable[[int, int, str], None]


def compare_text_only(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
) -> TextDiffResult:
    """Diff determinístico — sem IA."""
    return compute_text_diff(
        text_a,
        text_b,
        contract_id=contract_id,
        label_a=label_a,
        label_b=label_b,
    )


def compare_versions(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    path_a: str | None = None,
    path_b: str | None = None,
    *,
    analysis_mode: AnalysisMode | None = None,
    mode: AnalysisMode | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ContractDiffResult:
    """
    Compara duas versões: diff textual primeiro, depois modo escolhido.
    Opcionalmente mapeia alterações nos arquivos PDF/DOCX.
    """
    resolved_mode = analysis_mode or mode or AnalysisMode.CRITERIOSA
    total_steps = 3
    if progress_callback:
        progress_callback(0, total_steps, "Iniciando comparação…")

    if resolved_mode == AnalysisMode.CRITERIOSA and len(text_a) + len(text_b) >= 200_000:
        result = compare_contracts_full_document(
            text_a, text_b, label_a, label_b, contract_id
        )
    else:
        result = compare_contracts(
            text_a,
            text_b,
            label_a,
            label_b,
            contract_id,
            mode=resolved_mode,
            progress_callback=progress_callback,
        )

    if path_a or path_b:
        result.contractual_changes = attach_locations_to_changes(
            result.contractual_changes, path_a, path_b
        )

    if progress_callback:
        progress_callback(total_steps, total_steps, "Concluído")

    logger.info(
        "Análise concluída ({}): {} alterações ({} alto risco)",
        resolved_mode.value,
        len(result.contractual_changes),
        result.high_risk_count,
    )
    return result
