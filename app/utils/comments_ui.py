"""UI e fluxo de comentários ancorados no documento (upload, análise inicial e comparação)."""

from __future__ import annotations

import uuid
from pathlib import Path

import streamlit as st
from loguru import logger

from app.core import extractor, reviewer
from app.core.diff_index import DiffHunkIndex, location_label
from app.core.text_diff import compute_text_diff
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
    TextDiffResult,
)
from app.utils.document_ui import render_document_navigator
from app.utils.theme import section_title

_BUNDLES_KEY = "document_comments_bundles"
_STATUS_BADGE = {
    CommentStatus.ATTENDED: "✅ Atendido",
    CommentStatus.PARTIALLY: "⚠️ Parcial",
    CommentStatus.NOT_ATTENDED: "❌ Não atendido",
}

_STATUS_HELP = {
    CommentStatus.ATTENDED: (
        "O pedido do comentário foi implementado em um bloco de diferença textual "
        "entre a versão base e a revisada."
    ),
    CommentStatus.PARTIALLY: (
        "Parte do pedido foi atendida, mas falta algo relevante, ou a alteração é "
        "ambígua e merece revisão humana."
    ),
    CommentStatus.NOT_ATTENDED: (
        "Nenhum bloco de diferença textual implementa o pedido — o trecho permanece inalterado no diff."
    ),
}


def render_comment_status_legend() -> None:
    """Explica as categorias de avaliação de comentários."""
    with st.expander("ℹ️ Como interpretar as categorias de avaliação", expanded=False):
        st.markdown(
            """
**✅ Atendido** — o pedido aparece implementado em um **bloco de diferença textual**
entre a versão base e a revisada (pode ser fora do trecho do balão, mas sempre no diff).

**⚠️ Atendido parcialmente** — há alteração relacionada no diff, mas o pedido não foi
totalmente atendido ou a evidência não é conclusiva.

**❌ Não atendido** — nenhum bloco de diferença textual responde ao pedido;
o trecho correspondente está inalterado entre as versões.

A verificação usa **diff textual puro**: a IA recebe **todos** os blocos que mudaram
e verifica cada comentário contra cada um. Embeddings servem só para localização no PDF/DOCX
e para indicar qual bloco parece mais relacionado (não filtra o que vai para a IA).
A taxa de atendimento considera apenas os **plenamente atendidos** (verde).
Comentários parciais (amarelo) ainda exigem atenção.
            """
        )
        for status, badge in _STATUS_BADGE.items():
            st.caption(f"{badge}: {_STATUS_HELP[status]}")


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
    """Usa o próprio arquivo da versão (comentários no arquivo mais recente)."""
    from app.core.annotation_io import assert_writable, validate_document_path

    src = validate_document_path(source_path)
    assert_writable(src)
    current = bundle.annotated_file_path
    if current and Path(current).resolve() == src and src.exists():
        return str(src)
    bundle.annotated_file_path = str(src)
    _save_bundle(bundle)
    return str(src)


def _draft_from_extracted(raw: dict) -> DocumentCommentDraft:
    cid = raw.get("stable_id") or raw.get("id") or str(uuid.uuid4())[:8]
    return DocumentCommentDraft(
        comment_id=cid,
        comment_text=raw.get("comment_text", ""),
        anchor_text=raw.get("referenced_text") or None,
        source=DocumentCommentSource.EXTRACTED,
        page_hint=str(raw.get("page")) if raw.get("page") else None,
    )


def _persist_comment_record(version_id: str, draft: DocumentCommentDraft) -> None:
    db.save_comment_record(
        version_id,
        draft.comment_id,
        draft.comment_text,
        anchor_text=draft.anchor_text or "",
        source=draft.source.value,
        page_hint=draft.page_hint or "",
        parent_comment_id=draft.source_ref,
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
    stable_id = str(uuid.uuid4())[:8]
    if file_path and anchor_text:
        stable_id = extractor.compute_comment_stable_id(
            file_path,
            page=page_hint or "",
            author="manual",
            comment_text=comment_text.strip(),
            referenced_text=anchor_text or "",
        )
    draft = DocumentCommentDraft(
        comment_id=stable_id,
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
    _persist_comment_record(bundle.version_id, draft)
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
        stable = raw.get("stable_id") or draft.comment_id
        db.save_comment_record(
            bundle.version_id,
            stable,
            draft.comment_text,
            anchor_text=draft.anchor_text or "",
            source=draft.source.value,
            page_hint=draft.page_hint or "",
        )
        added += 1
    _save_bundle(bundle)
    return added


def _quick_applied_key(version_id: str) -> str:
    return f"quick_applied_comments_{version_id}"


def get_quick_applied_ids(version_id: str) -> set[str]:
    raw = st.session_state.get(_quick_applied_key(version_id), [])
    session_ids = set(raw) if isinstance(raw, (list, set)) else set()
    db_ids = {
        r.stable_id
        for r in db.get_comment_records(version_id)
        if r.quick_applied
    }
    return session_ids | db_ids


def mark_quick_applied(version_id: str, source_ref: str) -> None:
    applied = get_quick_applied_ids(version_id)
    applied.add(source_ref)
    st.session_state[_quick_applied_key(version_id)] = list(applied)
    db.set_comment_quick_applied(version_id, source_ref, True)


def apply_quick_comment_to_version(
    version,
    *,
    comment_text: str,
    anchor_text: str | None = None,
    locations: list | None = None,
    source_ref: str | None = None,
    percent_point: tuple[float, float] | None = None,
    percent_rect: tuple[float, float, float, float] | None = None,
    paragraph_index: int | None = None,
    page_num: int | None = None,
) -> str:
    """Grava um comentário diretamente no PDF/DOCX da versão (arquivo mais recente)."""
    bundle = get_comments_bundle(version.id, version.contract_id)
    work = _ensure_work_file(bundle, version.file_path)

    locs = list(locations or [])
    skip_search = percent_point is not None or percent_rect is not None or paragraph_index is not None
    if not locs and anchor_text and not skip_search:
        locs = find_in_document(work, anchor_text)
    if not locs and comment_text.strip() and not skip_search:
        locs = find_in_document(work, comment_text[:120])

    work = add_comment_to_document(
        work,
        comment_text.strip(),
        anchor_text=anchor_text,
        locations=locs,
        output_path=work,
        percent_point=percent_point,
        percent_rect=percent_rect,
        paragraph_index=paragraph_index,
        page_num=page_num,
    )
    bundle.annotated_file_path = work
    _save_bundle(bundle)

    if source_ref:
        mark_quick_applied(version.id, source_ref)
        try:
            from app.utils.inline_comments_ui import mark_queue_item_applied

            mark_queue_item_applied(version.id, source_ref)
        except Exception:
            pass

    return work


def render_annotated_download_button(
    version,
    *,
    key_prefix: str = "cmt",
    label: str = "⬇️ Baixar PDF com comentários",
) -> None:
    """Atalho compacto — painel completo em render_annotated_export_panel."""
    from app.utils.export_ui import render_annotated_export_panel

    render_annotated_export_panel(version, key_prefix=key_prefix, compact=True)


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


def count_comments_in_file(file_path: str) -> int:
    """Conta comentários/anotações no PDF ou DOCX (pré-visualização antes da análise)."""
    try:
        return len(extractor.extract_comments(file_path))
    except Exception as exc:
        logger.debug("Sem comentários em {}: {}", file_path, exc)
        return 0


def load_comments_for_version(version, contract_id: str) -> list[dict]:
    """Extrai comentários do arquivo da versão e prepara lista para a IA."""
    bundle = get_comments_bundle(version.id, contract_id)
    if not bundle.comments:
        load_comments_from_file(bundle, version.file_path)
    bundle = get_comments_bundle(version.id, contract_id)
    for c in bundle.comments:
        db.save_comment_record(
            version.id,
            c.comment_id,
            c.comment_text,
            anchor_text=c.anchor_text or "",
            source=c.source.value,
            page_hint=c.page_hint or "",
        )
    return [
        {
            "id": c.comment_id,
            "comment_text": c.comment_text,
            "referenced_text": c.anchor_text or "",
            "page": c.page_hint or 1,
        }
        for c in bundle.comments
    ]


def verify_comments_between_versions(
    base_version,
    new_version,
    contract_id: str,
    *,
    text_diff: TextDiffResult | None = None,
    diff_index: DiffHunkIndex | None = None,
    progress_callback=None,
    skip_llm: bool = False,
) -> CommentsReviewResult:
    raw_comments = load_comments_for_version(base_version, contract_id)

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

    stable_ids = [c.get("id") for c in raw_comments if c.get("id")]
    _ = db.get_comments_by_stable_ids(stable_ids)

    if text_diff is None:
        text_diff = compute_text_diff(
            base_version.extracted_text,
            new_version.extracted_text,
            contract_id=contract_id,
            label_a=getattr(base_version, "label", "Base") or "Base",
            label_b=getattr(new_version, "label", "Revisada") or "Revisada",
        )

    diff_index = diff_index or DiffHunkIndex.build(
        base_version.extracted_text,
        new_version.extracted_text,
        base_version.file_path,
        new_version.file_path,
        use_embeddings=not skip_llm,
    )
    text_diff.paragraph_hunks = diff_index.hunks

    result = reviewer.review_comments(
        raw_comments,
        base_version.extracted_text,
        new_version.extracted_text,
        text_diff,
        contract_id,
        skip_llm=skip_llm,
        progress_callback=progress_callback,
        path_base=base_version.file_path,
        path_new=new_version.file_path,
        diff_index=diff_index,
    )
    for rev in result.reviews:
        if rev.locations:
            continue
        anchor = rev.change_found or rev.referenced_excerpt or rev.original_comment
        if anchor:
            rev.locations = find_in_document(new_version.file_path, anchor)
    return result


def render_comment_verification_results(
    verification: CommentsReviewResult,
    *,
    new_version=None,
    key_prefix: str = "cmt_ver",
) -> None:
    """Painel principal: cada comentário do contrato base vs atendimento na nova versão."""
    try:
        from app.utils.comment_balloons import close_comment_modal_overlay

        close_comment_modal_overlay()
    except Exception:
        pass

    if verification.total_comments == 0:
        st.warning(
            "Nenhum comentário encontrado no **contrato com comentários**. "
            "Use um PDF/DOCX que tenha anotações de revisão (balões de comentário)."
        )
        return

    render_comment_status_legend()

    search_q = st.text_input(
        "Buscar comentário (Ctrl+F)",
        key=f"{key_prefix}_search",
        placeholder="Filtrar por texto, status ou cláusula…",
    ).strip().lower()

    c1, c2, c3 = st.columns(3)
    c1.metric("Atendidos", f"{verification.attended}/{verification.total_comments}")
    c2.metric("Parciais", verification.partially)
    c3.metric("Não atendidos", verification.not_attended)
    st.progress(
        verification.overall_attended_rate,
        text=f"Atendimento: {verification.overall_attended_rate:.0%}",
    )

    not_ok = [r for r in verification.reviews if r.status != CommentStatus.ATTENDED]
    if not_ok:
        st.error(f"**{len(not_ok)} pedido(s)** ainda exigem atenção na versão revisada.")

    reviews_to_show = verification.reviews
    if search_q:
        reviews_to_show = [
            r
            for r in verification.reviews
            if search_q
            in f"{r.original_comment} {r.justification} {r.status.value}".lower()
        ]

    if new_version:
        applied_ids = get_quick_applied_ids(new_version.id)
        pending_quick = [
            r
            for r in verification.reviews
            if review_needs_reinforcement(r) and r.comment_id not in applied_ids
        ]
        if pending_quick:
            st.markdown("**Comentar no PDF novo (1 clique)**")
            st.caption(
                "Aplica a sugestão da IA diretamente no arquivo revisado, "
                "no trecho correspondente — sem precisar editar ou confirmar em fila."
            )
            if st.button(
                f"✅ Comentar todos os pendentes no PDF ({len(pending_quick)})",
                type="primary",
                key=f"{key_prefix}_quick_all",
            ):
                try:
                    with st.spinner(f"Gravando {len(pending_quick)} comentário(s)..."):
                        for rev in pending_quick:
                            anchor = rev.referenced_excerpt or rev.change_found
                            apply_quick_comment_to_version(
                                new_version,
                                comment_text=suggest_reinforcement(rev),
                                anchor_text=anchor,
                                locations=rev.locations,
                                source_ref=rev.comment_id,
                            )
                    st.success(f"{len(pending_quick)} comentário(s) gravado(s) no PDF.")
                    st.session_state["bgf_show_save_cta"] = new_version.id
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

        from app.utils.export_ui import (
            get_annotated_work_path,
            render_annotated_export_panel,
            render_prominent_save_cta,
        )

        show_save = (
            get_annotated_work_path(new_version)
            or st.session_state.get("bgf_show_save_cta") == new_version.id
        )
        if show_save:
            st.markdown("### 💾 Salvar arquivo comentado")
            render_prominent_save_cta(
                new_version,
                key_prefix=f"{key_prefix}_top",
            )
            with st.expander("Mais opções de exportação", expanded=False):
                render_annotated_export_panel(
                    new_version,
                    key_prefix=f"{key_prefix}_export",
                    title="Salvar PDF comentado",
                    compact=True,
                )
            st.divider()

    for rev in reviews_to_show:
        badge = _STATUS_BADGE.get(rev.status, rev.status.value)
        icon = "✅" if rev.status == CommentStatus.ATTENDED else (
            "⚠️" if rev.status == CommentStatus.PARTIALLY else "❌"
        )
        with st.expander(f"{icon} {badge} — {rev.original_comment[:90]}…", expanded=rev.status != CommentStatus.ATTENDED):
            st.markdown(f"**Pedido:** {rev.original_comment}")
            if rev.referenced_excerpt:
                st.caption("Trecho referenciado no contrato anterior")
                st.code(rev.referenced_excerpt[:800])
            st.write(f"**Análise:** {rev.justification}")
            if rev.change_found:
                st.markdown("**O que mudou na nova versão:**")
                st.code(rev.change_found[:1200])
            if rev.locations or rev.locations_base:
                loc_parts = []
                for loc in rev.locations[:2]:
                    loc_parts.append(f"revisada {location_label(loc)}")
                for loc in rev.locations_base[:2]:
                    loc_parts.append(f"base {location_label(loc)}")
                if loc_parts:
                    st.caption("📍 " + " · ".join(loc_parts))
            if rev.suggested_response:
                st.markdown("**Sugestão de resposta ao cliente:**")
                st.write(rev.suggested_response)

            if new_version and review_needs_reinforcement(rev):
                applied_ids = get_quick_applied_ids(new_version.id)
                if rev.comment_id in applied_ids:
                    st.success("✅ Sugestão já gravada no arquivo mais recente.")
                else:
                    preview = (
                        f"Por favor, atender ao comentário anterior ainda pendente nesta versão:\n\n"
                        f"{rev.original_comment[:500]}"
                    )
                    with st.expander("Prévia do comentário (edite ao aceitar)", expanded=False):
                        st.write(preview)
                    if st.button(
                        "✅ Aceitar (editar e gravar)",
                        type="primary",
                        key=f"{key_prefix}_quick_{rev.comment_id}",
                        help="Abre o texto sugerido para você editar antes de gravar no arquivo mais recente.",
                    ):
                        st.session_state["bgf_open_cmt_id"] = rev.comment_id
                        st.rerun()

            if new_version and rev.locations:
                render_document_navigator(
                    new_version.file_path,
                    new_version.file_type,
                    excerpt_locations=rev.locations,
                    key_prefix=f"{key_prefix}_{rev.comment_id}",
                )


def render_paragraph_diff_locations(
    paragraph_hunks: list,
    *,
    path_base: str | None = None,
    path_new: str | None = None,
    path_base_type: str = "pdf",
    path_new_type: str = "pdf",
    key_prefix: str = "diff_loc",
) -> None:
    """Lista blocos de diff com localização no documento (índice por embeddings)."""
    from app.core.diff_index import format_hunk_block_with_location
    from app.models.schemas import TextDiffHunk

    if not paragraph_hunks:
        st.info("Nenhuma diferença textual entre as versões.")
        return

    st.caption(
        f"{len(paragraph_hunks)} bloco(s) alterado(s). "
        "Localização obtida no PDF/DOCX e indexada para busca rápida."
    )
    for i, raw in enumerate(paragraph_hunks, 1):
        # Após reload do Streamlit, isinstance pode falhar entre cópias da mesma classe.
        if isinstance(raw, TextDiffHunk):
            hunk = raw
        elif hasattr(raw, "model_dump"):
            hunk = TextDiffHunk.model_validate(raw.model_dump())
        else:
            hunk = TextDiffHunk.model_validate(raw)
        loc_hint = ""
        if hunk.locations_new:
            loc_hint = f" — revisada {location_label(hunk.locations_new[0])}"
        elif hunk.locations_base:
            loc_hint = f" — base {location_label(hunk.locations_base[0])}"
        with st.expander(f"Bloco {i} [{hunk.change_type}]{loc_hint}", expanded=i <= 2):
            st.markdown(format_hunk_block_with_location(hunk, index=i))
            if path_new and hunk.locations_new:
                render_document_navigator(
                    path_new,
                    path_new_type,
                    excerpt_locations=hunk.locations_new,
                    key_prefix=f"{key_prefix}_new_{hunk.hunk_id}",
                )
            elif path_base and hunk.locations_base:
                render_document_navigator(
                    path_base,
                    path_base_type,
                    excerpt_locations=hunk.locations_base,
                    key_prefix=f"{key_prefix}_base_{hunk.hunk_id}",
                )


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
                    try:
                        from types import SimpleNamespace

                        ver = SimpleNamespace(
                            id=new_bundle.version_id,
                            contract_id=new_bundle.contract_id,
                            file_path=new_file_path,
                        )
                        apply_quick_comment_to_version(
                            ver,
                            comment_text=edited,
                            anchor_text=rev.referenced_excerpt or rev.change_found,
                            locations=rev.locations,
                            source_ref=rev.comment_id,
                        )
                        st.session_state["bgf_show_save_cta"] = new_bundle.version_id
                        try:
                            from app.utils.comment_balloons import close_comment_modal_overlay

                            close_comment_modal_overlay()
                        except Exception:
                            pass
                        st.success("Reforço gravado no arquivo. Salve o documento com o botão abaixo.")
                        st.rerun()
                    except Exception as exc:
                        st.error(str(exc))

            if rev.locations and new_file_path:
                render_document_navigator(
                    new_file_path,
                    new_file_type,
                    excerpt_locations=rev.locations,
                    key_prefix=f"{key_prefix}_loc_{rev.comment_id}",
                )

    from types import SimpleNamespace

    from app.utils.export_ui import get_annotated_work_path, render_prominent_save_cta

    ver = SimpleNamespace(
        id=new_bundle.version_id,
        contract_id=new_bundle.contract_id,
        file_path=new_file_path,
    )
    if get_annotated_work_path(ver) or st.session_state.get("bgf_show_save_cta") == new_bundle.version_id:
        st.divider()
        st.markdown("### 💾 Salvar arquivo comentado")
        render_prominent_save_cta(
            ver,
            key_prefix=f"{key_prefix}_save",
            message="Use o botão abaixo para salvar o documento comentado no seu computador.",
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
    Lista de comentários, sugestões da análise e exportação.
    Entrada manual removida — use o workspace inline (clique no documento).
    """
    bundle = get_comments_bundle(version.id, version.contract_id)
    file_path = version.file_path
    file_type = version.file_type

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
        search = st.text_input(
            "Buscar comentário (Ctrl+F)",
            key=f"{key_prefix}_search",
            placeholder="Filtrar por texto, status ou âncora…",
        )
        q = search.strip().lower()
        filtered = bundle.comments
        if q:
            filtered = [
                d
                for d in bundle.comments
                if q in d.comment_text.lower()
                or q in (d.anchor_text or "").lower()
                or q in d.source.value.lower()
            ]
        st.markdown(f"**Lista ({len(filtered)}/{len(bundle.comments)} comentário(s))**")
        for i, draft in enumerate(filtered):
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
            from app.utils.export_ui import render_annotated_export_panel

            render_annotated_export_panel(
                version,
                key_prefix=f"{key_prefix}_export",
                title="Salvar contrato com comentários",
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
        st.caption("Nenhum comentário na lista. Use as sugestões da análise ou comente no documento.")

    return bundle
