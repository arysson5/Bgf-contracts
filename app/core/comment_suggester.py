"""Sugestões de comentários de revisão via LLM."""

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger

from app.core.comment_style_profile import (
    fallback_matrix_comment,
    style_guide_for_llm,
)
from app.core.llm import get_llm
from app.models.schemas import (
    ChangeRisk,
    CommentReview,
    CommentStatus,
    MatrixItemResult,
    MatrixItemStatus,
    MatrixParameterCheck,
    RequirementCheck,
)

_STYLE_GUIDE = style_guide_for_llm()

_SUGGEST_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            "Você é revisor jurídico da BGF revisando contratos brasileiros. "
            "Redija comentários para inserção em PDF (balão de revisão), no mesmo padrão "
            "dos exemplos abaixo.\n\n{style_guide}",
        ),
        ("user", "{context}"),
    ]
)


def _suggest(context: str, fallback: str) -> str:
    try:
        llm = get_llm(temperature=0.2)
        text = (
            llm.invoke(
                _SUGGEST_PROMPT.format_messages(context=context, style_guide=_STYLE_GUIDE)
            ).content
            or ""
        ).strip()
        return text or fallback
    except Exception as exc:
        logger.warning("Falha ao sugerir comentário: {}", exc)
        return fallback


def suggest_for_matrix_gap(check: MatrixParameterCheck) -> str:
    ctx = (
        f"Lacuna na matriz de verificação.\n"
        f"Categoria: {check.categoria}\n"
        f"Parâmetro: {check.parametro_verificacao}\n"
        f"Risco esperado: {check.risco_padrao or 'não informado'}\n"
        f"Observação da análise: {check.observation}\n"
        f"Trecho encontrado (se houver): {check.found_excerpt or 'ausente'}\n"
        f"Referência: {check.page_hint or 'não indicada'}\n\n"
        "Redija um comentário de revisão pedindo que o contrato seja alterado para atender ao parâmetro."
    )
    fallback = fallback_matrix_comment(
        check.categoria,
        check.parametro_verificacao,
        check.observation,
        page_hint=check.page_hint,
    )
    return _suggest(ctx, fallback)


def suggest_for_checklist_gap(check: RequirementCheck) -> str:
    ctx = (
        f"Requisito não atendido no contrato.\n"
        f"Requisito: {check.requirement_text}\n"
        f"Observação: {check.observation}\n"
        f"Trecho: {check.found_excerpt or 'não localizado'}\n\n"
        "Redija um comentário pedindo inclusão ou correção no documento."
    )
    fallback = (
        "Por favor, incluir ou corrigir no contrato o seguinte requisito:\n\n"
        f"{check.requirement_text}. {check.observation}"
    )
    return _suggest(ctx, fallback)


def suggest_for_matrix_divergence(item: MatrixItemResult) -> str:
    ctx = (
        f"Divergência entre proposta e contrato.\n"
        f"Categoria: {item.categoria}\n"
        f"Parâmetro: {item.parametro_verificacao}\n"
        f"Status: {item.status.value}\n"
        f"Divergência: {item.divergencia}\n"
        f"Impacto: {item.impacto}\n"
        f"Evidência contrato: {item.contrato_evidencia or '—'}\n"
        f"Evidência proposta: {item.proposta_evidencia or '—'}\n"
        f"Recomendação da análise: {item.recomendacao}\n\n"
        "Redija um comentário no contrato pedindo alinhamento com a proposta."
    )
    fallback = fallback_matrix_comment(
        item.categoria,
        item.parametro_verificacao,
        item.recomendacao or item.divergencia or "Divergência entre proposta e contrato.",
    )
    return _suggest(ctx, fallback)


def suggest_reinforcement(review: CommentReview) -> str:
    ctx = (
        f"Comentário anterior do revisor não foi plenamente atendido na nova versão.\n"
        f"Comentário original: {review.original_comment}\n"
        f"Status: {review.status.value}\n"
        f"Justificativa: {review.justification}\n"
        f"Alteração encontrada: {review.change_found or 'nenhuma'}\n"
        f"Trecho referenciado: {review.referenced_excerpt or 'não identificado'}\n\n"
        "Redija um comentário reforçado, claro e firme, pedindo a correção ainda pendente."
    )
    fallback = (
        "Por favor, atender ao comentário anterior ainda pendente nesta versão:\n\n"
        f"{review.original_comment[:500]}\n\n"
        f"Justificativa da análise: {review.justification}"
    )
    return _suggest(ctx, fallback)


def matrix_item_needs_comment(item: MatrixItemResult) -> bool:
    return item.status in (
        MatrixItemStatus.DIVERGENTE,
        MatrixItemStatus.AUSENTE_CONTRATO,
        MatrixItemStatus.OBRIGACAO_ADICIONAL,
    ) or item.risk_level in (ChangeRisk.HIGH, ChangeRisk.MEDIUM)


def review_needs_reinforcement(review: CommentReview) -> bool:
    return review.status in (CommentStatus.NOT_ATTENDED, CommentStatus.PARTIALLY)
