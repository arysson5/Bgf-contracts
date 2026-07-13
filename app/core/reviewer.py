"""Pipeline de revisão de comentários via Google Gemini — baseado em diff textual puro."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable

from langchain_core.prompts import ChatPromptTemplate
from loguru import logger
from rapidfuzz import fuzz
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.diff_index import DiffHunkIndex
from app.core.llm import get_llm_pro
from app.core.text_diff import (
    format_hunk_block,
    paragraph_diff_hunks,
)
from app.models.schemas import (
    CommentReview,
    CommentsReviewResult,
    CommentStatus,
    TextDiffHunk,
    TextDiffResult,
)

ProgressCallback = Callable[[int, int, str], None]

SYSTEM_PROMPT = """Você é um revisor jurídico brasileiro especializado em contratos.
Sua tarefa é verificar, com RIGOR, se cada comentário (instrução de revisão) foi atendido
na nova versão do documento ou seja leve cada comentario como uma função ou objetivo pedido de alteraçãp para buscarna nova versão.

FONTES DE EVIDÊNCIA — use APENAS os blocos de diferença textual fornecidos:
- O sistema já comparou as duas versões com diff textual determinístico.
- Tudo que NÃO aparece nos blocos de diferença está INALTERADO entre as versões.
- Portanto, se o pedido do comentário não estiver implementado em algum bloco de diff,
  ele NÃO foi atendido — não presuma alterações fora do diff.

Classifique cada comentário em EXATAMENTE uma categoria:

**attended (Atendido)** — use SOMENTE quando:
1. ha inidicios que O pedido específico do comentário foi implementado na versão nova;
2. Há evidência clara em um ou mais blocos de diferença que comprove a correção;
3. A alteração atende ao pedido de alteração (não basta tema parecido);
4. Você consegue citar o bloco de diff que comprova o atendimento.

**partially (Atendido parcialmente)** — use quando:
- Parte do pedido aparece nos blocos de diff, mas falta algo relevante;
- Há alteração relacionada, porém incompleta ou ambígua;
- Na dúvida entre attended e not_attended, use partially.

**not_attended (Não atendido)** — use quando:
- Nenhum bloco de diferença implementa o pedido do comentário;
- Os blocos mostram o trecho âncora inalterado ou mudanças irrelevantes;
- O cliente ignorou a solicitação (o diff não reflete o pedido).

REGRAS:
- Julgue pelo PEDIDO ESPECÍFICO do comentário.
- Percorra TODOS os blocos de diferença fornecidos — o atendimento pode estar em qualquer um.
- Trechos fora dos blocos listados estão inalterados entre as versões.
- Se nenhum bloco implementar o pedido, classifique not_attended.
- Em caso de dúvida real, prefira partially ou not_attended.
- Se o pedido do comentário não estiver implementado em algum bloco de diff, ele NÃO foi atendido — não presuma alterações fora do diff.
- Responda em português brasileiro.

Formato de saída (campos obrigatórios):
- status: attended | partially | not_attended
- justification: string
- change_found: string (trecho «depois» que comprova; vazio se não houver)
- suggested_response: string"""

USER_PROMPT = """## Comentário do administrador (instrução a verificar)
{comment_text}

## Trecho âncora no documento base (onde o balão foi colocado)
{original_excerpt}

## TODOS os blocos de diferença textual entre as versões ({block_count} bloco(s))
Analise cada bloco abaixo e verifique se o pedido do comentário foi atendido em algum deles.

{all_diff_blocks}

## Indício automático (não substitui sua análise — percorra todos os blocos)
{evidence_summary}

Determine:
1. status: attended | partially | not_attended
2. justification: explicação objetiva (2–4 frases) citando o número do bloco de diff ou a ausência de atendimento
3. change_found: citação do trecho «depois» que comprova a alteração (ou null)
4. suggested_response: texto curto para o admin enviar ao cliente"""


def _normalize_for_match(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    return re.sub(r"[^\w\s]", "", t)


def _keyword_tokens(text: str, min_len: int = 4) -> set[str]:
    stop = {
        "para", "como", "esse", "esta", "este", "essa", "pelo", "pela", "sobre",
        "deve", "será", "sendo", "favor", "ajustar", "alterar", "incluir", "trecho",
        "clausula", "contrato", "versao", "texto", "pedido", "por favor",
    }
    words = re.findall(r"\b[a-záàâãéêíóôõúç]{4,}\b", _normalize_for_match(text))
    return {w for w in words if w not in stop}


def _extract_search_signals(comment_text: str, original_excerpt: str) -> dict[str, list[str]]:
    combined = f"{comment_text} {original_excerpt}"
    money = list(dict.fromkeys(re.findall(r"R\$\s*[\d.,]+", combined, flags=re.I)))
    clauses = list(dict.fromkeys(re.findall(r"\b\d+\.\d+(?:\.\d+)?\b", combined)))
    numbers = list(dict.fromkeys(re.findall(r"\b\d{3,}\b", combined)))[:6]
    quoted = re.findall(r"[«\"']([^»\"']{8,120})[»\"']", combined)
    return {
        "money": money,
        "clauses": clauses,
        "numbers": numbers,
        "quoted": quoted[:4],
    }


def _paragraph_relevance(
    para: str,
    signals: dict[str, list[str]],
    keywords: set[str],
) -> float:
    if not para.strip():
        return 0.0
    score = 0.0
    para_norm = _normalize_for_match(para)
    para_compact = para.replace(" ", "").lower()

    for kw in keywords:
        if kw in para_norm:
            score += 1.5

    for money in signals.get("money", []):
        if money.replace(" ", "").lower() in para_compact:
            score += 6.0

    for clause in signals.get("clauses", []):
        if clause in para:
            score += 3.0

    for num in signals.get("numbers", []):
        if num in para:
            score += 2.0

    for quote in signals.get("quoted", []):
        if _fuzzy_contains(quote, para, threshold=82):
            score += 4.0

    return score


def _hunk_text_blob(hunk: TextDiffHunk) -> str:
    return " ".join(filter(None, [hunk.text_a, hunk.text_b])).strip()


def _score_hunk_relevance(
    hunk: TextDiffHunk,
    comment_text: str,
    original_excerpt: str,
) -> float:
    blob = _hunk_text_blob(hunk)
    if not blob:
        return 0.0
    keywords = _keyword_tokens(comment_text) | _keyword_tokens(original_excerpt)
    signals = _extract_search_signals(comment_text, original_excerpt)
    score = _paragraph_relevance(blob, signals, keywords)

    if original_excerpt:
        if _fuzzy_contains(original_excerpt, hunk.text_a or ""):
            score += 5.0
        elif _fuzzy_contains(original_excerpt, hunk.text_b or ""):
            score += 4.0
        elif fuzz.partial_ratio(original_excerpt, hunk.text_a or "") >= 72:
            score += 3.0

    if comment_text and _fuzzy_contains(comment_text[:100], blob, threshold=70):
        score += 2.0

    return score


def select_relevant_hunks(
    comment_text: str,
    original_excerpt: str,
    all_changed: list[TextDiffHunk],
    *,
    min_score: float = 2.5,
    max_hunks: int = 8,
) -> list[TextDiffHunk]:
    """Seleciona blocos de diff potencialmente ligados ao comentário."""
    scored: list[tuple[float, TextDiffHunk]] = []
    for hunk in all_changed:
        score = _score_hunk_relevance(hunk, comment_text, original_excerpt)
        if score >= min_score:
            scored.append((score, hunk))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [h for _, h in scored[:max_hunks]]


def format_hunks_for_review(hunks: list[TextDiffHunk]) -> str:
    if not hunks:
        return "(nenhum bloco de diferença relacionado a este comentário)"
    return "\n\n".join(format_hunk_block(h, index=i) for i, h in enumerate(hunks, 1))


def _evidence_strength(
    comment_text: str,
    original_excerpt: str,
    relevant_blocks: str,
) -> tuple[str, float]:
    keywords = _keyword_tokens(comment_text) | _keyword_tokens(original_excerpt)
    signals = _extract_search_signals(comment_text, original_excerpt)

    if not relevant_blocks.strip() or relevant_blocks.startswith("(nenhum"):
        return "nenhuma — sem blocos de diff relacionados", 0.0

    score = min(8.0, _paragraph_relevance(relevant_blocks, signals, keywords))

    if signals.get("money"):
        for money in signals["money"]:
            if money.replace(" ", "").lower() in relevant_blocks.replace(" ", "").lower():
                score += 2.0
                break

    score = round(min(score, 10.0), 1)

    if score >= 7.0:
        label = "forte — blocos de diff claramente ligados ao pedido"
    elif score >= 4.0:
        label = "moderada — indícios no diff, exige verificação criteriosa"
    else:
        label = "fraca — pouca ou nenhuma evidência no diff"

    return label, score


def _navigation_hunks(
    index: DiffHunkIndex,
    review: CommentReview,
    comment_text: str,
    original_excerpt: str,
) -> list[TextDiffHunk]:
    """Blocos para exibir localização na UI após a análise."""
    if review.status == CommentStatus.NOT_ATTENDED:
        return []

    cited = (review.change_found or "").strip()
    if cited:
        matched: list[TextDiffHunk] = []
        for hunk in index.hunks:
            blob = " ".join(filter(None, [hunk.text_a, hunk.text_b]))
            if _fuzzy_contains(cited, blob, threshold=70):
                matched.append(hunk)
        if matched:
            return matched[:4]

    ranked = index.rank_blocks(comment_text, original_excerpt, top_k=3)
    return [s.hunk for s in ranked]


def _evidence_hint(
    index: DiffHunkIndex,
    comment_text: str,
    original_excerpt: str,
    all_diff_blocks: str,
) -> tuple[str, float]:
    """Indício automático — não filtra o que vai para a IA."""
    if not index.hunks:
        return "nenhum bloco de diff entre as versões", 0.0

    ranked = index.rank_blocks(comment_text, original_excerpt, top_k=1)
    base_score = min(8.0, _paragraph_relevance(
        all_diff_blocks,
        _extract_search_signals(comment_text, original_excerpt),
        _keyword_tokens(comment_text) | _keyword_tokens(original_excerpt),
    ))

    if ranked:
        top = ranked[0]
        block_num = next(
            (i + 1 for i, h in enumerate(index.hunks) if h.hunk_id == top.hunk.hunk_id),
            1,
        )
        rank_pct = round(top.score * 100)
        label = (
            f"maior similaridade automática: bloco {block_num} "
            f"({rank_pct}%, via {top.source})"
        )
        score = round(min(10.0, base_score * 0.4 + top.score * 6.0), 1)
        return label, score

    return "nenhum bloco com similaridade destacada — analise todos manualmente", round(base_score, 1)


def _format_evidence_summary(strength_label: str, score: float) -> str:
    return f"Indício automático: {score}/10 ({strength_label})."


def _calibrate_review(
    review: CommentReview,
    all_diff_blocks: str,
    evidence_score: float,
    *,
    has_diff_blocks: bool,
) -> CommentReview:
    """Só corrige attended quando não há nenhum bloco de diff (não rebaixa por score)."""
    if review.status != CommentStatus.ATTENDED:
        return review

    if not has_diff_blocks or all_diff_blocks.startswith("(nenhum"):
        review.status = CommentStatus.NOT_ATTENDED
        review.justification = (
            "Revisão criteriosa: nenhum bloco de diferença textual entre as versões. "
            + review.justification
        )
    return review


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=30))
def _call_llm_review(
    comment_id: str,
    comment_text: str,
    original_excerpt: str,
    referenced: str | None,
    all_diff_blocks: str,
    block_count: int,
    evidence_summary: str,
) -> CommentReview:
    llm = get_llm_pro(temperature=0)
    structured = llm.with_structured_output(CommentReview)
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("user", USER_PROMPT)]
    )
    chain = prompt | structured
    result: CommentReview = chain.invoke(
        {
            "comment_text": comment_text,
            "original_excerpt": original_excerpt or "(âncora não identificada no PDF)",
            "all_diff_blocks": all_diff_blocks,
            "block_count": block_count,
            "evidence_summary": evidence_summary,
        }
    )
    result.comment_id = comment_id
    result.original_comment = comment_text
    if referenced and not result.referenced_excerpt:
        result.referenced_excerpt = referenced
    return result


def _find_best_excerpt(text: str, referenced: str, threshold: int = 72) -> str:
    if not referenced or not text:
        return ""
    if referenced in text:
        return referenced
    ref_len = len(referenced)
    best_score = 0
    best_slice = ""
    step = max(30, ref_len // 6)
    for i in range(0, max(1, len(text) - ref_len + 1), step):
        window = text[i : i + ref_len + 120]
        score = fuzz.partial_ratio(referenced, window)
        if score > best_score:
            best_score = score
            best_slice = window[: ref_len + 250]
    if best_score >= threshold:
        return best_slice.strip()
    return referenced


def _fuzzy_contains(needle: str, haystack: str, threshold: int = 78) -> bool:
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    n = _normalize_for_match(needle)
    h = _normalize_for_match(haystack)
    if len(n) < 8:
        return n in h
    if fuzz.partial_ratio(n, h) >= threshold:
        return True
    for size in (80, 50, 35):
        frag = needle[:size]
        if len(frag) >= 12 and frag in haystack:
            return True
    return False


def _apply_hunk_metadata(
    review: CommentReview,
    hunks: list[TextDiffHunk],
    index: DiffHunkIndex,
) -> CommentReview:
    review.matched_hunk_ids = [h.hunk_id for h in hunks]
    review.locations = index.collect_locations(hunks, side="new")
    review.locations_base = index.collect_locations(hunks, side="base")
    return review


def _local_diff_verdict(
    comment_text: str,
    original_excerpt: str,
    relevant_hunks: list[TextDiffHunk],
    *,
    top_similarity: float = 0.0,
) -> CommentReview | None:
    """Atalho local quando o diff mostra alteração clara ligada ao pedido."""
    if not relevant_hunks:
        return None

    top = relevant_hunks[0]
    if top_similarity >= 0.5:
        relevance = top_similarity * 10.0
    else:
        relevance = _score_hunk_relevance(top, comment_text, original_excerpt)
    if relevance < 5.0:
        return None

    change_found = top.text_b or top.text_a or format_hunks_for_review([top])[:400]

    return CommentReview(
        comment_id="",
        original_comment=comment_text,
        referenced_excerpt=original_excerpt,
        status=CommentStatus.ATTENDED,
        justification=(
            "Alteração ligada ao pedido identificada nos blocos de diff textual "
            f"(relevância {relevance:.0f})."
        ),
        change_found=change_found[:800],
        suggested_response="Alteração identificada e atendida na nova versão.",
    )


def _not_attended_no_diff(comment_id: str, comment_text: str, referenced: str, anchor: str) -> CommentReview:
    return CommentReview(
        comment_id=comment_id,
        original_comment=comment_text,
        referenced_excerpt=referenced or anchor or None,
        status=CommentStatus.NOT_ATTENDED,
        justification=(
            "Nenhum bloco de diferença textual entre as versões está relacionado a este comentário. "
            "O trecho correspondente permanece inalterado no diff."
        ),
        suggested_response=(
            "O pedido não foi refletido nas alterações enviadas. Solicite revisão ao cliente."
        ),
    )


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


async def _review_one_async(
    cmt: dict,
    text_original: str,
    index: DiffHunkIndex,
    all_diff_digest: str,
    semaphore: asyncio.Semaphore,
    *,
    skip_llm: bool = False,
) -> CommentReview:
    cid = cmt.get("id", "")
    comment_text = cmt.get("comment_text", "")
    referenced = cmt.get("referenced_text", "") or ""

    original_excerpt = _find_best_excerpt(text_original, referenced)
    if not original_excerpt.strip() and comment_text:
        original_excerpt = comment_text[:300]

    block_count = len(index.hunks)
    strength_label, evidence_score = _evidence_hint(
        index, comment_text, original_excerpt, all_diff_digest
    )
    evidence_summary = _format_evidence_summary(strength_label, evidence_score)

    if not index.hunks:
        return _not_attended_no_diff(cid, comment_text, referenced, original_excerpt)

    if skip_llm:
        ranked = index.rank_blocks(comment_text, original_excerpt, top_k=5)
        nav_hunks = [s.hunk for s in ranked] if ranked else index.hunks[:3]
        review = CommentReview(
            comment_id=cid,
            original_comment=comment_text,
            referenced_excerpt=referenced or original_excerpt or None,
            status=CommentStatus.PARTIALLY,
            justification=(
                f"{evidence_summary} {block_count} bloco(s) de diff enviados para revisão manual. "
                "Use «Comparar com IA» para análise completa de cada comentário contra todos os blocos."
            ),
            change_found=all_diff_digest[:1200],
            suggested_response="Verificar manualmente se o pedido foi integralmente atendido no diff.",
        )
        return _apply_hunk_metadata(review, nav_hunks, index)

    async with semaphore:
        try:
            review = await asyncio.to_thread(
                _call_llm_review,
                cid,
                comment_text,
                original_excerpt,
                referenced or None,
                all_diff_digest,
                block_count,
                evidence_summary,
            )
            calibrated = _calibrate_review(
                review,
                all_diff_digest,
                evidence_score,
                has_diff_blocks=block_count > 0,
            )
            if not calibrated.justification.startswith("Indício"):
                calibrated.justification = f"{evidence_summary} {calibrated.justification}"
            nav_hunks = _navigation_hunks(index, calibrated, comment_text, original_excerpt)
            return _apply_hunk_metadata(calibrated, nav_hunks, index)
        except Exception as exc:
            logger.error("Erro ao revisar comentário {}: {}", cid, exc)
            review = CommentReview(
                comment_id=cid,
                original_comment=comment_text,
                referenced_excerpt=referenced or None,
                status=CommentStatus.PARTIALLY,
                justification=f"Erro na análise automática — revisar manualmente: {exc}",
                suggested_response="Não foi possível classificar automaticamente. Revise este ponto.",
            )
            return _apply_hunk_metadata(review, [], index)


async def _review_all_async(
    comments: list[dict],
    text_original: str,
    text_new: str,
    index: DiffHunkIndex,
    progress_callback: ProgressCallback | None,
    *,
    skip_llm: bool = False,
) -> list[CommentReview]:
    semaphore = asyncio.Semaphore(5)
    total = len(comments)
    all_diff_digest = index.full_digest()

    async def _run_index(i: int, cmt: dict) -> CommentReview:
        if progress_callback:
            progress_callback(i, total, f"Comentário {i + 1}/{total}")
        logger.info("Revisando comentário {} (página {})", cmt.get("id"), cmt.get("page"))
        return await _review_one_async(
            cmt,
            text_original,
            index,
            all_diff_digest,
            semaphore,
            skip_llm=skip_llm,
        )

    tasks = [_run_index(i, c) for i, c in enumerate(comments)]
    reviews = await asyncio.gather(*tasks)
    if progress_callback:
        progress_callback(total, total, "Comentários verificados")
    return list(reviews)


def review_comments(
    comments: list[dict],
    text_original: str,
    text_new: str,
    text_diff: TextDiffResult,
    contract_id: str,
    *,
    progress_callback: ProgressCallback | None = None,
    skip_llm: bool = False,
    path_base: str | None = None,
    path_new: str | None = None,
    diff_index: DiffHunkIndex | None = None,
) -> CommentsReviewResult:
    if not comments:
        return CommentsReviewResult(
            contract_id=contract_id,
            total_comments=0,
            attended=0,
            not_attended=0,
            partially=0,
            reviews=[],
            overall_attended_rate=0.0,
            admin_summary="Nenhum comentário para verificar.",
        )

    index = diff_index or DiffHunkIndex.build(
        text_original,
        text_new,
        path_base,
        path_new,
        use_embeddings=not skip_llm,
    )
    if text_diff is not None:
        text_diff.paragraph_hunks = index.hunks

    reviews = asyncio.run(
        _review_all_async(
            comments,
            text_original,
            text_new,
            index,
            progress_callback,
            skip_llm=skip_llm,
        )
    )

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
