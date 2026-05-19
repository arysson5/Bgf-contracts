"""Comparação entre versões — delega à análise contratual (IA)."""

from app.core.contract_comparator import compare_contracts
from app.core.document_locator import attach_locations_to_changes
from app.models.schemas import ContractDiffResult
from loguru import logger


def compare_versions(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    contract_id: str,
    path_a: str | None = None,
    path_b: str | None = None,
) -> ContractDiffResult:
    """
    Análise contratual criteriosa entre duas versões (não diff de caracteres).
    Opcionalmente mapeia alterações nos arquivos PDF/DOCX.
    """
    result = compare_contracts(text_a, text_b, label_a, label_b, contract_id)

    if path_a or path_b:
        result.contractual_changes = attach_locations_to_changes(
            result.contractual_changes, path_a, path_b
        )

    logger.info(
        "Análise concluída: {} alterações ({} alto risco)",
        len(result.contractual_changes),
        result.high_risk_count,
    )
    return result
