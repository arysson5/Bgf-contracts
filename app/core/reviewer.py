"""Pipeline de revisão de comentários via Google Gemini."""

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from rapidfuzz import fuzz
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.llm import get_llm
from app.models.schemas import (
    CommentReview,
    CommentsReviewResult,
    CommentStatus,
    ContractDiffResult,
    DiffType,
)


SYSTEM_PROMPT = """Você analisa contratos jurídicos brasileiros e verifica se solicitações
feitas em comentários de revisão foram atendidas na nova versão do documento."""

USER_PROMPT = """Comentário do administrador:
{comment_text}

Trecho original do contrato referenciado:
{original_excerpt}

Trecho na nova versão do cliente (o que mudou):
{new_excerpt}

Determine:
1. status: attended, not_attended ou partially
2. justification em português
3. change_found: o que mudou (ou null)
4. suggested_response: texto para o admin enviar ao cliente sobre este ponto"""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def _call_llm_review(
    comment_id: str,
    comment_text: str,
    original_excerpt: str,
    new_excerpt: str,
    referenced: str | None,
) -> CommentReview:
    llm = get_llm(temperature=0)
    structured = llm.with_structured_output(CommentReview)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    result: CommentReview = chain.invoke(
        {
            "comment_text": comment_text,
            "original_excerpt": original_excerpt or "(trecho não identificado)",
            "new_excerpt": new_excerpt or "sem alteração identificada nesse trecho",
        }
    )
    result.comment_id = comment_id
    result.original_comment = comment_text
    if referenced and not result.referenced_excerpt:
        result.referenced_excerpt = referenced
    return result


def _find_best_excerpt(text: str, referenced: str, threshold: int = 80) -> str:
    if not referenced or not text:
        return ""
    if referenced in text:
        return referenced
    # Busca por janela deslizante aproximada
    ref_len = len(referenced)
    best_score = 0
    best_slice = ""
    step = max(50, ref_len // 4)
    for i in range(0, max(1, len(text) - ref_len + 1), step):
        window = text[i : i + ref_len + 100]
        score = fuzz.partial_ratio(referenced, window)
        if score > best_score:
            best_score = score
            best_slice = window[: ref_len + 200]
    if best_score >= threshold:
        return best_slice.strip()
    return referenced


def _excerpt_changed_in_diff(excerpt: str, diff_result: ContractDiffResult) -> str:
    if not excerpt:
        return ""
    parts: list[str] = []
    for ch in diff_result.contractual_changes or []:
        texts = [ch.original_text or "", ch.new_text or "", ch.description]
        if any(excerpt[:40] in (t or "") for t in texts if len(excerpt) >= 10):
            parts.append(f"[{ch.clause_reference}] {ch.new_text or ch.description}"[:600])
    if parts:
        return "\n".join(parts[:5])
    # legado diff_blocks
    for block in diff_result.diff_blocks or []:
        if block.block_type in (DiffType.ADDED, DiffType.REMOVED):
            if excerpt[:40] in block.text:
                parts.append(block.text[:500])
    return "\n".join(parts[:5]) if parts else ""


def generate_admin_summary(reviews: list[CommentReview]) -> str:
    attended = sum(1 for r in reviews if r.status == CommentStatus.ATTENDED)
    partial = sum(1 for r in reviews if r.status == CommentStatus.PARTIALLY)
    not_att = sum(1 for r in reviews if r.status == CommentStatus.NOT_ATTENDED)
    total = len(reviews)
    pending = [r.original_comment for r in reviews if r.status != CommentStatus.ATTENDED]
    pending_text = "; ".join(pending[:5]) if pending else "nenhum"
    return (
        f"{attended} de {total} comentários foram plenamente atendidos "
        f"({partial} parcialmente, {not_att} não atendidos). "
        f"Os pontos que ainda precisam de atenção: {pending_text}."
    )


def review_comments(
    comments: list[dict],
    text_original: str,
    text_new: str,
    diff_result: ContractDiffResult,
    contract_id: str,
) -> CommentsReviewResult:
    reviews: list[CommentReview] = []

    for cmt in comments:
        cid = cmt.get("id", "")
        comment_text = cmt.get("comment_text", "")
        referenced = cmt.get("referenced_text", "") or ""

        logger.info("Revisando comentário {} (página {})", cid, cmt.get("page"))

        original_excerpt = _find_best_excerpt(text_original, referenced)
        change_hint = _excerpt_changed_in_diff(original_excerpt, diff_result)
        new_excerpt = change_hint or _find_best_excerpt(text_new, original_excerpt or referenced)

        try:
            review = _call_llm_review(
                cid, comment_text, original_excerpt, new_excerpt, referenced or None
            )
        except Exception as exc:
            logger.error("Erro ao revisar comentário {}: {}", cid, exc)
            review = CommentReview(
                comment_id=cid,
                original_comment=comment_text,
                referenced_excerpt=referenced or None,
                status=CommentStatus.NOT_ATTENDED,
                justification=f"Erro na análise automática: {exc}",
                suggested_response="Não foi possível gerar sugestão automaticamente.",
            )

        reviews.append(review)

    attended = sum(1 for r in reviews if r.status == CommentStatus.ATTENDED)
    partial = sum(1 for r in reviews if r.status == CommentStatus.PARTIALLY)
    not_att = sum(1 for r in reviews if r.status == CommentStatus.NOT_ATTENDED)
    total = len(reviews)
    rate = attended / total if total else 0.0

    return CommentsReviewResult(
        contract_id=contract_id,
        total_comments=total,
        attended=attended,
        not_attended=not_att,
        partially=partial,
        reviews=reviews,
        overall_attended_rate=round(rate, 4),
        admin_summary=generate_admin_summary(reviews),
    )
