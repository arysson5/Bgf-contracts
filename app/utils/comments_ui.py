"""UI e fluxo de comentários ancorados no documento (upload, análise inicial e comparação)."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

import streamlit as st
from loguru import logger

from app.core import extractor, reviewer
from app.core.comment_suggester import (
    review_needs_reinforcement,
    suggest_for_checklist_gap,
    suggest_for_matrix_divergence,
    suggest_for_matrix_gap,
    suggest_reinforcement,
)
from app.core.document_annotator import add_comment_to_document
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import (
    CommentReview,
    CommentStatus,
    CommentsReviewResult,
    ContractDiffResult,
    DocumentCommentDraft,
    DocumentCommentSource,
    DocumentCommentsBundle,
    MatrixParameterCheck,
    ProposalContractMatrixResult,
    RequirementCheck,
)
from app.utils.document_ui import render_document_navigator
from app.utils.theme import section_title

_BUNDLES_KEY = "document_comments_bundles"
_STATUS_BADGE = {
    CommentStatus.ATTENDED: "✅ Atendido",
    CommentStatus.PARTIALLY: "⚠️ Parcial",
    CommentStatus.NOT_ATTENDED: "❌ Não atendido",
}


def _bundles_store() -> dict[str, dict]:
    if _BUNDLES_KEY not in st.session_state:
        st.session_state[_BUNDLES_KEY] = {}
    return st.session_state[_BUNDLES_KEY]


def get_comments_bundle(version_id: str, contract_id: str) -> DocumentCommentsBundle:
    store = _bundles_store()
    if version_id not in store:
        store[version_id] = DocumentCommentsBundle(
            version_id=version_id, contract_id=contract_id
        ).model_dump()
    return DocumentCommentsBundle.model_validate(store[version_id])


def _save_bundle(bundle: DocumentCommentsBundle) -> None:
    _bundles_store()[bundle.version_id] = bundle.model_dump()


def _ensure_work_file(bundle: DocumentCommentsBundle, source_path: str) -> str:
    if bundle.annotated_file_path and Path(bundle.annotated_file_path).exists():
        return bundle.annotated_file_path
    ext = Path(source_path).suffix
    dest = Path(source_path).parent / f"{Path(source_path).stem}_revisao{ext}"
    shutil.copy2(source_path, dest)
    bundle.annotated_file_path = str(dest)
    _save_bundle(bundle)
    return str(dest)


def _draft_from_extracted(raw: dict) -> DocumentCommentDraft:
    return DocumentCommentDraft(
        comment_id=raw.get("id") or str(uuid.uuid4())[:8],
        comment_text=raw.get("comment_text", ""),
        anchor_text=raw.get("referenced_text") or None,
        source=DocumentCommentSource.EXTRACTED,
        page_hint=str(raw.get("page")) if raw.get("page") else None,
    )


def add_comment_draft(
    bundle: DocumentCommentsBundle,
    *,
    comment_text: str,
    anchor_text: str | None = None,
    source: DocumentCommentSource = DocumentCommentSource.MANUAL,
    source_ref: str | None = None,
    page_hint: str | None = None,
    file_path: str | None = None,
    file_type: str | None = None,
) -> DocumentCommentDraft:
    draft = DocumentCommentDraft(
        comment_id=str(uuid.uuid4())[:8],
        comment_text=comment_text.strip(),
        anchor_text=(anchor_text or "").strip() or None,
        source=source,
        source_ref=source_ref,
        page_hint=page_hint,
    )
    if file_path and draft.anchor_text:
        draft.locations = find_in_document(file_path, draft.anchor_text)
    elif file_path and draft.comment_text:
        draft.locations = find_in_document(file_path, draft.comment_text[:120])
    bundle.comments.append(draft)
    _save_bundle(bundle)
    return draft


def load_comments_from_file(bundle: DocumentCommentsBundle, file_path: str) -> int:
    extracted = extractor.extract_comments(file_path)
    existing_ids = {c.comment_id for c in bundle.comments}
    added = 0
    for raw in extracted:
        draft = _draft_from_extracted(raw)
        if draft.comment_id in existing_ids:
            continue
        if file_path:
            anchor = draft.anchor_text or draft.comment_text
            if anchor:
                draft.locations = find_in_document(file_path, anchor)
        bundle.comments.append(draft)
        added += 1
    _save_bundle(bundle)
    return added


def apply_comments_to_file(bundle: DocumentCommentsBundle, source_path: str) -> str:
    work = _ensure_work_file(bundle, source_path)
    to_apply = [c for c in bundle.comments if c.include_in_export and c.comment_text.strip()]
    if not to_apply:
        raise ValueError("Nenhum comentário marcado para exportar.")

    for draft in to_apply:
        work = add_comment_to_document(
            work,
            draft.comment_text,
            anchor_text=draft.anchor_text,
            locations=draft.locations,
            output_path=work,
        )
    bundle.annotated_file_path = work
    _save_bundle(bundle)
    logger.info("Aplicados {} comentário(s) em {}", len(to_apply), work)
    return work


def verify_comments_between_versions(
    base_version,
    new_version,
    contract_id: str,
    diff_result: ContractDiffResult,
) -> CommentsReviewResult:
    base_bundle = get_comments_bundle(base_version.id, contract_id)
    if not base_bundle.comments:
        load_comments_from_file(base_bundle, base_version.file_path)

    raw_comments = [
        {
            "id": c.comment_id,
            "comment_text": c.comment_text,
            "referenced_text": c.anchor_text or "",
            "page": c.page_hint or 1,
        }
        for c in base_bundle.comments
    ]
    if not raw_comments:
        load_comments_from_file(base_bundle, base_version.file_path)
        raw_comments = [
            {
                "id": c.comment_id,
                "comment_text": c.comment_text,
                "referenced_text": c.anchor_text or "",
                "page": c.page_hint or 1,
            }
            for c in get_comments_bundle(base_version.id, contract_id).comments
        ]

    if not raw_comments:
        return CommentsReviewResult(
            contract_id=contract_id,
            total_comments=0,
            attended=0,
            not_attended=0,
            partially=0,
            reviews=[],
            overall_attended_rate=0.0,
            admin_summary="Nenhum comentário encontrado na versão base para verificar.",
        )

    result = reviewer.review_comments(
        raw_comments,
        base_version.extracted_text,
        new_version.extracted_text,
        diff_result,
        contract_id,
    )
    for rev in result.reviews:
        anchor = rev.referenced_excerpt or rev.change_found or rev.original_comment
        if anchor:
            rev.locations = find_in_document(new_version.file_path, anchor)
    return result


def render_comment_suggestions(
    bundle: DocumentCommentsBundle,
    file_path: str,
    file_type: str,
    *,
    matrix_checks: list[MatrixParameterCheck] | None = None,
    checklist_checks: list[RequirementCheck] | None = None,
    matrix_items: list | None = None,
    key_prefix: str = "cmt",
) -> None:
    """Exibe sugestões LLM a partir de lacunas/divergências e permite adicionar à lista."""
    suggestions: list[tuple[str, str, str | None, DocumentCommentSource, str | None]] = []

    if matrix_checks:
        for ch in matrix_checks:
            if ch.present:
                continue
            text = suggest_for_matrix_gap(ch)
            anchor = ch.found_excerpt or ch.page_hint
            suggestions.append(
                (f"{key_prefix}_mg_{ch.item_id}", text, anchor, DocumentCommentSource.MATRIX_GAP, ch.item_id)
            )

    if checklist_checks:
        for ch in checklist_checks:
            if ch.present:
                continue
            text = suggest_for_checklist_gap(ch)
            anchor = ch.found_excerpt or ch.page_hint
            suggestions.append(
                (f"{key_prefix}_ck_{ch.requirement_id}", text, anchor, DocumentCommentSource.CHECKLIST_GAP, ch.requirement_id)
            )

    if matrix_items:
        from app.core.comment_suggester import matrix_item_needs_comment

        for it in matrix_items:
            if not matrix_item_needs_comment(it):
                continue
            text = suggest_for_matrix_divergence(it)
            anchor = it.contrato_evidencia or it.proposta_evidencia
            suggestions.append(
                (f"{key_prefix}_md_{it.item_id}", text, anchor, DocumentCommentSource.MATRIX_DIVERGENCE, it.item_id)
            )

    if not suggestions:
        return

    st.markdown("**Sugestões da análise (IA)**")
    for sk, text, anchor, source, ref in suggestions[:12]:
        with st.expander(f"Sugestão — {ref or sk}"):
            edited = st.text_area("Texto do comentário", text, height=80, key=f"sg_{sk}")
            if st.button("➕ Adicionar à lista de comentários", key=f"add_{sk}"):
                add_comment_draft(
                    bundle,
                    comment_text=edited,
                    anchor_text=anchor,
                    source=source,
                    source_ref=ref,
                    file_path=file_path,
                )
                st.success("Comentário adicionado.")
                st.rerun()


def render_verification_results(
    review_result: CommentsReviewResult,
    new_bundle: DocumentCommentsBundle,
    new_file_path: str,
    new_file_type: str,
    *,
    key_prefix: str = "ver",
) -> None:
    if not review_result.reviews:
        st.info(review_result.admin_summary)
        return

    st.info(review_result.admin_summary)
    c1, c2, c3 = st.columns(3)
    c1.metric("Atendidos", review_result.attended)
    c2.metric("Parciais", review_result.partially)
    c3.metric("Não atendidos", review_result.not_attended)

    for rev in review_result.reviews:
        badge = _STATUS_BADGE.get(rev.status, rev.status.value)
        with st.expander(f"{badge} — {rev.original_comment[:80]}…"):
            st.write("**Comentário original:**", rev.original_comment)
            st.write("**Justificativa:**", rev.justification)
            if rev.change_found:
                st.caption(f"Alteração: {rev.change_found[:400]}")

            if review_needs_reinforcement(rev):
                reinforced = suggest_reinforcement(rev)
                edited = st.text_area(
                    "Comentário reforçado sugerido",
                    reinforced,
                    height=90,
                    key=f"{key_prefix}_rf_{rev.comment_id}",
                )
                if st.button("➕ Incluir reforço na versão nova", key=f"{key_prefix}_add_rf_{rev.comment_id}"):
                    add_comment_draft(
                        new_bundle,
                        comment_text=edited,
                        anchor_text=rev.referenced_excerpt or rev.change_found,
                        source=DocumentCommentSource.REINFORCEMENT,
                        source_ref=rev.comment_id,
                        file_path=new_file_path,
                    )
                    st.success("Reforço adicionado à lista da versão nova.")
                    st.rerun()

            if rev.locations and new_file_path:
                render_document_navigator(
                    new_file_path,
                    new_file_type,
                    excerpt_locations=rev.locations,
                    key_prefix=f"{key_prefix}_loc_{rev.comment_id}",
                )


def render_comments_panel(
    version,
    *,
    matrix_checks: list[MatrixParameterCheck] | None = None,
    checklist_checks: list[RequirementCheck] | None = None,
    matrix_items: list | None = None,
    verification: CommentsReviewResult | None = None,
    key_prefix: str = "cmt",
) -> DocumentCommentsBundle:
    """
    Painel completo: manual, extração, sugestões, lista, salvar no arquivo e download.
    """
    section_title("Comentários de revisão no documento")
    st.caption(
        "Insira comentários fixados no PDF/DOCX pedindo alterações. "
        "Na comparação de versões, o sistema verifica se os comentários da versão base foram atendidos."
    )

    bundle = get_comments_bundle(version.id, version.contract_id)
    file_path = version.file_path
    file_type = version.file_type

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button("📎 Ler comentários já existentes no arquivo", key=f"{key_prefix}_load_file"):
            n = load_comments_from_file(bundle, file_path)
            st.success(f"{n} comentário(s) importado(s) do documento.") if n else st.warning(
                "Nenhum comentário nativo encontrado no arquivo."
            )
            st.rerun()
    with col_b:
        if bundle.comments and st.button("🗑️ Limpar lista", key=f"{key_prefix}_clear"):
            bundle.comments = []
            _save_bundle(bundle)
            st.rerun()

    st.markdown("**Novo comentário**")
    anchor_in = st.text_input(
        "Trecho do contrato (âncora)",
        key=f"{key_prefix}_anchor",
        placeholder="Cole o trecho que deve ser alterado",
    )
    text_in = st.text_area(
        "Texto do comentário",
        key=f"{key_prefix}_text",
        height=90,
        placeholder="Solicitar alteração, inclusão ou correção…",
    )
    if st.button("Adicionar comentário", key=f"{key_prefix}_add_manual") and text_in.strip():
        add_comment_draft(
            bundle,
            comment_text=text_in,
            anchor_text=anchor_in or None,
            file_path=file_path,
        )
        st.success("Adicionado.")
        st.rerun()

    render_comment_suggestions(
        bundle,
        file_path,
        file_type,
        matrix_checks=matrix_checks,
        checklist_checks=checklist_checks,
        matrix_items=matrix_items,
        key_prefix=key_prefix,
    )

    if verification:
        st.divider()
        st.markdown("**Verificação dos comentários (versão base → nova)**")
        render_verification_results(
            verification,
            bundle,
            file_path,
            file_type,
            key_prefix=f"{key_prefix}_ver",
        )

    if bundle.comments:
        st.divider()
        st.markdown(f"**Lista ({len(bundle.comments)} comentário(s))**")
        for i, draft in enumerate(bundle.comments):
            src_label = draft.source.value.replace("_", " ")
            with st.expander(f"[{src_label}] {draft.comment_text[:70]}…"):
                edited = st.text_area(
                    "Texto",
                    draft.comment_text,
                    key=f"{key_prefix}_ed_{draft.comment_id}",
                    height=70,
                )
                inc = st.checkbox(
                    "Incluir ao salvar no arquivo",
                    value=draft.include_in_export,
                    key=f"{key_prefix}_inc_{draft.comment_id}",
                )
                if edited != draft.comment_text or inc != draft.include_in_export:
                    draft.comment_text = edited
                    draft.include_in_export = inc
                    _save_bundle(bundle)
                if draft.anchor_text:
                    st.caption(f"Âncora: {draft.anchor_text[:200]}")
                if draft.locations:
                    render_document_navigator(
                        file_path,
                        file_type,
                        excerpt_locations=draft.locations,
                        key_prefix=f"{key_prefix}_d_{i}",
                    )
                if st.button("Remover", key=f"{key_prefix}_rm_{draft.comment_id}"):
                    bundle.comments = [c for c in bundle.comments if c.comment_id != draft.comment_id]
                    _save_bundle(bundle)
                    st.rerun()

        st.divider()
        if st.button(
            "💾 Salvar todos os comentários no arquivo",
            type="primary",
            key=f"{key_prefix}_save_file",
        ):
            try:
                out = apply_comments_to_file(bundle, file_path)
                st.success(f"Comentários gravados em: {Path(out).name}")
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

        work = bundle.annotated_file_path
        if work and Path(work).exists():
            with open(work, "rb") as f:
                st.download_button(
                    "⬇️ Baixar contrato com comentários",
                    f.read(),
                    file_name=Path(work).name,
                    key=f"{key_prefix}_dl",
                )
            if file_type == "pdf":
                from app.utils.pdf_ui import show_pdf

                show_pdf(work, height=480, key=f"{key_prefix}_preview_pdf")
            else:
                from app.core.docx_viewer import render_docx_paragraphs_html

                st.markdown(render_docx_paragraphs_html(work), unsafe_allow_html=True)

        if st.button("Salvar lista no histórico", key=f"{key_prefix}_save_db"):
            db.save_analysis_result(version.id, "document_comments", bundle)
            st.success("Lista de comentários salva no histórico.")

    else:
        st.caption("Nenhum comentário na lista. Use sugestões da análise ou adicione manualmente.")

    return bundle
