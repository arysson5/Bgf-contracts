"""Comparação contratual entre versões — diff textual, IA híbrida e comentários."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import uuid
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import differ, extractor
from app.core.diff_index import DiffHunkIndex
from app.core.text_diff import compute_text_diff
from app.db import database as db
from app.models.schemas import (
    AnalysisMode,
    ChangeRisk,
    CommentsReviewResult,
    ContractDiffResult,
    TextDiffResult,
)
from app.utils.comments_ui import (
    count_comments_in_file,
    render_comment_verification_results,
    render_paragraph_diff_locations,
    verify_comments_between_versions,
)
from app.utils.document_ui import render_side_by_side_documents
from app.utils.analysis_session import (
    clear_compare_analysis_results,
    compare_token_matches,
    set_compare_analysis_token,
)
from app.utils.sync_scroll import ensure_sync_scroll_handler, sync_scroll_hint
from app.utils.settings import get_settings
from app.utils.theme import page_header, render_page_footer, section_title, setup_page
from app.utils.data_cache import clear_data_cache
from app.utils.active_contract import (
    render_active_contract_banner,
    version_select_index,
)
from app.utils.ui import (
    render_compare_version_pair,
    render_contract_browse_selector,
    save_temp_upload,
    save_uploaded_file,
)

setup_page("Comparar Versões")
settings = get_settings()

page_header(
    "Comparar versões",
    "Diff textual estilo PDF24, validação por regras ou análise criteriosa com IA nos trechos confirmados.",
)

render_active_contract_banner(context="compare")

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}

_ANALYSIS_LABELS = {
    "Comparar textos (sem IA)": AnalysisMode.TEXT_DIFF,
    "Diferenças": AnalysisMode.DIFERENCAS,
    "Validação": AnalysisMode.VALIDACAO,
    "Criteriosa (IA nos trechos)": AnalysisMode.CRITERIOSA,
}


def _analysis_mode_from_session() -> AnalysisMode:
    label = st.session_state.get("compare_analysis_mode", "Comparar textos (sem IA)")
    return _ANALYSIS_LABELS.get(label, AnalysisMode.TEXT_DIFF)


def _skip_llm_for_mode(mode: AnalysisMode) -> bool:
    return mode in (AnalysisMode.TEXT_DIFF, AnalysisMode.DIFERENCAS, AnalysisMode.VALIDACAO)


def _skip_llm_for_comment_review(mode: AnalysisMode) -> bool:
    """Comentários usam IA em qualquer modo «Comparar com IA»; só diff puro dispensa."""
    return mode == AnalysisMode.TEXT_DIFF


def _render_contractual_results(
    result: ContractDiffResult,
    path_a: str | None,
    path_b: str | None,
    type_a: str,
    type_b: str,
    label_a: str,
    label_b: str,
    *,
    save_version_id: str | None = None,
    version_new=None,
    version_base=None,
    comment_verification: CommentsReviewResult | None = None,
    text_diff: TextDiffResult | None = None,
    analysis_mode: AnalysisMode = AnalysisMode.TEXT_DIFF,
) -> None:
    section_title("Resultado")

    try:
        from app.utils.comment_balloons import close_comment_modal_overlay

        close_comment_modal_overlay()
        if st.query_params.get("bgf_inc") or st.query_params.get("bgf_cmt"):
            st.query_params.clear()
    except Exception:
        pass

    if version_new:
        from app.utils.export_ui import get_annotated_work_path, render_prominent_save_cta

        if (
            get_annotated_work_path(version_new)
            or st.session_state.get("bgf_show_save_cta") == version_new.id
        ):
            render_prominent_save_cta(
                version_new,
                key_prefix="cmp_save_banner",
                message="Comentário incluído no arquivo revisado. **Salve o PDF/DOCX** no seu computador:",
            )
            st.divider()

    tab_docs, tab_comments, tab_diff = st.tabs(
        ["Documentos lado a lado", "Comentários", "Alterações"]
    )

    diff_html = text_diff.side_by_side_html if text_diff else None
    if not diff_html and analysis_mode in (AnalysisMode.TEXT_DIFF, AnalysisMode.DIFERENCAS):
        diff_html = result.executive_summary  # fallback

    show_comment_balloons = (
        analysis_mode != AnalysisMode.TEXT_DIFF
        and comment_verification is not None
        and comment_verification.total_comments > 0
    )

    with tab_docs:
        ensure_sync_scroll_handler()
        if path_a and path_b:
            render_side_by_side_documents(
                path_a,
                type_a,
                path_b,
                type_b,
                label_a=label_a,
                label_b=label_b,
                changes=result.contractual_changes,
                text_diff_html=diff_html if not show_comment_balloons else None,
                comment_reviews=(
                    comment_verification.reviews if show_comment_balloons else None
                ),
                new_version=version_new if show_comment_balloons else None,
                key_prefix="cmp_sbs",
            )
        elif text_diff and text_diff.side_by_side_html:
            st.markdown(text_diff.side_by_side_html, unsafe_allow_html=True)
            sync_scroll_hint()
        else:
            st.warning("Arquivos não disponíveis para visualização.")

    with tab_comments:
        if comment_verification:
            render_comment_verification_results(
                comment_verification,
                new_version=version_new,
                key_prefix="cmp_cmt_ver",
            )
        else:
            st.info("Nenhum comentário na versão base para verificar nesta comparação.")

    with tab_diff:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Alterações materiais", result.material_changes_count)
        c2.metric("Alto risco", result.high_risk_count)
        c3.metric("Similaridade", f"{result.similarity_score:.0%}" if result.similarity_score else "—")
        c4.metric("Atenção", "Sim" if result.has_significant_changes else "Não")
        if result.executive_summary:
            st.info(result.executive_summary)
        if result.recommendation:
            st.success(result.recommendation)
        if text_diff and text_diff.inline_diff_html:
            with st.expander("Visão mesclada (inline)", expanded=False):
                st.markdown(text_diff.inline_diff_html, unsafe_allow_html=True)
        if text_diff and text_diff.paragraph_hunks:
            st.markdown("**Blocos de diferença (com localização)**")
            render_paragraph_diff_locations(
                text_diff.paragraph_hunks,
                path_base=path_a,
                path_new=path_b,
                path_base_type=type_a,
                path_new_type=type_b,
                key_prefix="cmp_diff_blk",
            )
        if not result.contractual_changes:
            st.success("Nenhuma alteração material identificada entre as versões.")
        for ch in result.contractual_changes:
            icon = RISK_ICON.get(ch.risk_level, "•")
            attn = " ⚠️" if ch.requires_attention else ""
            with st.expander(f"{icon} {ch.clause_reference} — {ch.title}{attn}"):
                st.write(ch.description)
                st.caption(
                    f"**Categoria:** {ch.category.value} | **Risco:** {ch.risk_level.value}"
                )
                if ch.legal_impact:
                    st.write(f"**Impacto jurídico:** {ch.legal_impact}")
                if ch.original_text:
                    st.markdown("**Texto anterior:**")
                    st.code(ch.original_text[:2000])
                if ch.new_text:
                    st.markdown("**Texto na versão revisada:**")
                    st.code(ch.new_text[:2000])

    if save_version_id and st.button("Salvar análise", key="save_contractual"):
        if analysis_mode == AnalysisMode.TEXT_DIFF and text_diff:
            db.save_analysis_result(save_version_id, "text_diff", text_diff)
        else:
            db.save_analysis_result(save_version_id, "diff", result)
        if comment_verification and comment_verification.total_comments:
            db.save_analysis_result(save_version_id, "comments", comment_verification)
        clear_data_cache()
        st.success("Análise salva. Consulte em **Histórico**.")


def _run_compare(
    text_a: str,
    text_b: str,
    label_a: str,
    label_b: str,
    path_a: str | None,
    path_b: str | None,
    contract_id: str,
    *,
    mode: AnalysisMode,
    progress_bar,
    status_caption,
) -> tuple[ContractDiffResult | None, TextDiffResult | None]:
    text_diff_result: TextDiffResult | None = None

    def _on_progress(step: int, total: int, label: str) -> None:
        pct = step / total if total else 0.0
        progress_bar.progress(min(1.0, pct), text=label)
        status_caption.caption(label)

    try:
        if mode == AnalysisMode.TEXT_DIFF:
            status_caption.caption("Fase 1/2: calculando diff textual…")
            progress_bar.progress(0.2, text="Diff textual…")
            text_diff_result = differ.compare_text_only(
                text_a, text_b, label_a, label_b, contract_id
            )
            progress_bar.progress(0.6, text="Montando resultado…")
            result = differ.compare_versions(
                text_a,
                text_b,
                label_a,
                label_b,
                contract_id,
                path_a=path_a,
                path_b=path_b,
                mode=AnalysisMode.TEXT_DIFF,
                progress_callback=_on_progress,
            )
        else:
            status_caption.caption("Fase 1/3: extraindo e comparando textos…")
            result = differ.compare_versions(
                text_a,
                text_b,
                label_a,
                label_b,
                contract_id,
                path_a=path_a,
                path_b=path_b,
                mode=mode,
                progress_callback=_on_progress,
            )
            text_diff_result = compute_text_diff(
                text_a, text_b, contract_id=contract_id, label_a=label_a, label_b=label_b
            )
        progress_bar.progress(1.0, text="Comparação concluída")
        return result, text_diff_result
    except ValueError as exc:
        st.error(str(exc))
        return None, None
    except Exception as exc:
        logger.exception("Erro na análise contratual")
        _show_analysis_error(exc)
        return None, None


def _show_analysis_error(exc: Exception) -> None:
    msg = str(exc)
    if "1114" in msg or "c10.dll" in msg.lower() or "PyTorch" in msg:
        st.error("Ambiente com PyTorch quebrado (WinError 1114). O app não precisa de torch.")
        st.info(
            "`.venv\\Scripts\\pip.exe uninstall -y torch torchvision torchaudio transformers unstructured` "
            "e reinicie o Streamlit."
        )
    else:
        st.warning(f"Erro na análise: {msg}. Tente novamente.")


def _run_full_compare(
    base_v,
    new_v,
    contract_id: str,
    *,
    label_a: str,
    label_b: str,
    path_a: str,
    path_b: str,
    text_a: str,
    text_b: str,
    save_version_id: str | None = None,
    mode: AnalysisMode,
) -> None:
    progress_bar = st.progress(0.0, text="Iniciando comparação…")
    status_caption = st.empty()

    result, text_diff = _run_compare(
        text_a,
        text_b,
        label_a,
        label_b,
        path_a,
        path_b,
        contract_id,
        mode=mode,
        progress_bar=progress_bar,
        status_caption=status_caption,
    )
    if not result:
        return

    diff_index: DiffHunkIndex | None = None
    if text_diff and text_a and text_b:
        diff_index = DiffHunkIndex.build(
            text_a,
            text_b,
            path_a,
            path_b,
            use_embeddings=not _skip_llm_for_comment_review(mode),
        )
        text_diff.paragraph_hunks = diff_index.hunks

    skip_llm = _skip_llm_for_mode(mode)
    skip_llm_comments = _skip_llm_for_comment_review(mode)
    verification: CommentsReviewResult | None = None
    n_comments = count_comments_in_file(path_a)

    if n_comments:
        ia_cmt = "com IA" if not skip_llm_comments else "regras locais (sem IA)"
        status_caption.caption(
            f"Fase {'2/2' if skip_llm else '3/3'}: verificando {n_comments} comentário(s) {ia_cmt}…"
        )

        def _cmt_progress(cur: int, total: int, lbl: str) -> None:
            base_pct = 0.7 if not skip_llm else 0.5
            progress_bar.progress(
                base_pct + (cur / total) * (1.0 - base_pct) if total else 1.0,
                text=lbl,
            )
            status_caption.caption(lbl)

        verification = verify_comments_between_versions(
            base_v,
            new_v,
            contract_id,
            text_diff=text_diff,
            diff_index=diff_index if text_diff else None,
            progress_callback=_cmt_progress,
            skip_llm=skip_llm_comments,
        )
    else:
        verification = CommentsReviewResult(
            contract_id=contract_id,
            total_comments=0,
            attended=0,
            not_attended=0,
            partially=0,
            reviews=[],
            overall_attended_rate=0.0,
            admin_summary="Nenhum comentário na versão base.",
        )

    progress_bar.progress(1.0, text="Análise concluída")
    status_caption.success("Comparação finalizada.")

    st.session_state.last_diff_result = result
    st.session_state.last_text_diff_result = text_diff
    st.session_state.last_comment_verification = verification
    st.session_state.last_compare_mode = mode.value
    st.session_state.last_regression_result = None


def _compare_analysis_token(
    kind: str,
    *,
    path_a: str | None = None,
    path_b: str | None = None,
    version_a_id: str | None = None,
    version_b_id: str | None = None,
    mode: AnalysisMode | None = None,
) -> str:
    mode_val = mode.value if mode else ""
    if kind == "saved":
        return f"saved:{version_a_id}:{version_b_id}:{mode_val}"
    if kind == "hybrid":
        return f"hybrid:{version_a_id}:{path_b}:{mode_val}"
    return f"quick:{path_a}:{path_b}:{mode_val}"


def _show_compare_results(ctx: dict) -> None:
    if st.session_state.get("compare_mode_kind") != ctx.get("kind"):
        return
    if not st.session_state.get("last_diff_result"):
        return
    token = ctx.get("analysis_token")
    if token and not compare_token_matches(token):
        return
    mode_val = st.session_state.get("last_compare_mode", AnalysisMode.TEXT_DIFF.value)
    try:
        mode = AnalysisMode(mode_val)
    except ValueError:
        mode = AnalysisMode.TEXT_DIFF
    st.divider()
    _render_contractual_results(
        st.session_state.last_diff_result,
        ctx["path_a"],
        ctx["path_b"],
        ctx["type_a"],
        ctx["type_b"],
        ctx["label_a"],
        ctx["label_b"],
        save_version_id=ctx.get("save_version_id"),
        version_new=ctx.get("version_new"),
        version_base=ctx.get("version_base"),
        comment_verification=st.session_state.get("last_comment_verification"),
        text_diff=st.session_state.get("last_text_diff_result"),
        analysis_mode=mode,
    )


def _diff_section() -> None:
    section_title("Tipo de análise")
    top_kind = st.radio(
        "Escolha o tipo",
        ["Comparar textos", "Comparar com IA"],
        horizontal=True,
        key="compare_top_kind",
    )
    if top_kind == "Comparar textos":
        st.session_state.compare_analysis_mode = "Comparar textos (sem IA)"
    else:
        ia_labels = ["Diferenças", "Validação", "Criteriosa (IA nos trechos)"]
        ia_map = {
            "Diferenças": "Diferenças",
            "Validação": "Validação",
            "Criteriosa (IA nos trechos)": "Criteriosa (IA nos trechos)",
        }
        ia_sel = st.radio(
            "Modo IA",
            ia_labels,
            horizontal=True,
            key="compare_ia_submode",
        )
        st.session_state.compare_analysis_mode = ia_map[ia_sel]
        st.caption(
            "**Diferenças**: diff textual convertido em alterações. "
            "**Validação**: regras + fuzzy nos trechos. "
            "**Criteriosa**: Gemini Pro só nos hunks confirmados. "
            "**Comentários**: sempre analisados por IA (Gemini Pro) neste modo."
        )

    section_title("Origem dos arquivos")
    mode_options = [
        "Última versão salva × novo arquivo",
        "Enviar os dois arquivos",
        "Duas versões salvas",
    ]
    default_mode = (
        mode_options[0] if st.session_state.get("active_contract_id") else mode_options[1]
    )
    if "compare_input_mode" not in st.session_state:
        st.session_state.compare_input_mode = default_mode

    mode = st.radio(
        "Como comparar",
        mode_options,
        horizontal=True,
        key="compare_input_mode",
    )

    if mode == mode_options[0]:
        _diff_hybrid_last_vs_upload()
    elif mode == mode_options[1]:
        _diff_quick_two_uploads()
    else:
        _diff_two_saved_versions()


def _diff_hybrid_last_vs_upload() -> None:
    contract_id = render_contract_browse_selector("cmp_hybrid", sync_active=True)
    if not contract_id:
        st.stop()

    versions = db.get_versions(contract_id)
    if not versions:
        st.info(
            "Nenhuma versão salva. Cadastre em **Upload & Análise inicial** "
            "ou use «Enviar os dois arquivos»."
        )
        st.stop()

    from app.utils.active_contract import version_option_label

    if len(versions) > 1:
        labels = [version_option_label(v) for v in versions]
        id_map = {lbl: v.id for lbl, v in zip(labels, versions)}
        base_idx = version_select_index(
            versions,
            st.session_state.get("compare_base_version_id"),
            len(versions) - 1,
        )
        sel = st.selectbox(
            "Versão com comentários",
            labels,
            index=base_idx,
            key="hybrid_base_ver",
        )
        va = db.get_version(id_map[sel])
        st.session_state.compare_base_version_id = va.id
    else:
        va = versions[-1]

    n_base = count_comments_in_file(va.file_path)
    if n_base:
        st.caption(f"**{n_base}** comentário(s) em v{va.version_number} — {va.label}")
    else:
        st.warning("Nenhum comentário detectado nesta versão.")

    file_b = st.file_uploader(
        "Versão revisada do cliente (PDF ou DOCX)",
        type=["pdf", "docx"],
        key="hybrid_new_file",
    )
    default_label = st.session_state.get("upload_version_label_default", "Versão revisada")
    label_b = st.text_input("Nome da revisão", value=default_label, key="hybrid_new_label")
    save_as_version = st.checkbox(
        "Salvar como nova versão do contrato",
        value=True,
        key="hybrid_save_version",
    )

    analysis_mode = _analysis_mode_from_session()

    if st.button("Comparar versões", type="primary", key="cmp_run_hybrid"):
        if not file_b:
            st.warning("Envie o arquivo da versão revisada.")
        else:
            clear_compare_analysis_results()
            try:
                with st.spinner("Extraindo texto da versão revisada…"):
                    if save_as_version:
                        path_b = save_uploaded_file(file_b, settings.contracts_path)
                    else:
                        path_b = save_temp_upload(file_b, settings.contracts_path, prefix="b")
                    text_b, tb = extractor.extract_text(path_b)

                new_v: SimpleNamespace
                save_vid: str | None = None

                if save_as_version:
                    saved = db.add_version(
                        contract_id,
                        label_b,
                        path_b,
                        tb.value,
                        text_b,
                    )
                    new_v = saved
                    save_vid = saved.id
                    clear_data_cache()
                    from app.utils.active_contract import apply_active_contract

                    apply_active_contract(contract_id, force=True)
                    st.success(f"Versão salva: v{saved.version_number} — {saved.label}")
                else:
                    uid = uuid.uuid4().hex[:8]
                    new_v = SimpleNamespace(
                        id=f"{contract_id}-upload-{uid}",
                        contract_id=contract_id,
                        file_path=path_b,
                        file_type=tb.value,
                        extracted_text=text_b,
                        label=label_b,
                    )

                _run_full_compare(
                    va,
                    new_v,
                    contract_id,
                    label_a=va.label,
                    label_b=label_b,
                    path_a=va.file_path,
                    path_b=path_b,
                    text_a=va.extracted_text,
                    text_b=text_b,
                    save_version_id=save_vid,
                    mode=analysis_mode,
                )
                analysis_token = _compare_analysis_token(
                    "hybrid",
                    path_b=path_b,
                    version_a_id=va.id,
                    mode=analysis_mode,
                )
                set_compare_analysis_token(analysis_token)
                st.session_state.hybrid_compare_ctx = {
                    "kind": "hybrid",
                    "path_a": va.file_path,
                    "path_b": path_b,
                    "type_a": va.file_type,
                    "type_b": tb.value,
                    "label_a": va.label,
                    "label_b": label_b,
                    "version_new": new_v,
                    "version_base": va,
                    "save_version_id": save_vid,
                    "analysis_token": analysis_token,
                }
                st.session_state.compare_mode_kind = "hybrid"
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    ctx = st.session_state.get("hybrid_compare_ctx") or {}
    _show_compare_results(ctx)


def _diff_quick_two_uploads() -> None:
    c1, c2 = st.columns(2)
    with c1:
        file_a = st.file_uploader(
            "Com comentários (PDF ou DOCX)",
            type=["pdf", "docx"],
            key="quick_a",
        )
        label_a = st.text_input("Nome", value="Com comentários", key="ql_a")
    with c2:
        file_b = st.file_uploader(
            "Revisado (PDF ou DOCX)",
            type=["pdf", "docx"],
            key="quick_b",
        )
        label_b = st.text_input("Nome", value="Versão revisada", key="ql_b")

    analysis_mode = _analysis_mode_from_session()

    if st.button("Comparar versões", type="primary", key="cmp_run_quick"):
        if not file_a or not file_b:
            st.warning("Envie os dois arquivos.")
        else:
            clear_compare_analysis_results()
            try:
                with st.spinner("Extraindo texto…"):
                    uid = uuid.uuid4().hex[:8]
                    path_a = save_temp_upload(file_a, settings.contracts_path, prefix="a")
                    path_b = save_temp_upload(file_b, settings.contracts_path, prefix="b")
                    text_a, ta = extractor.extract_text(path_a)
                    text_b, tb = extractor.extract_text(path_b)
                cid = f"quick-{uid}"
                base_v = SimpleNamespace(
                    id=f"{cid}-base",
                    contract_id=cid,
                    file_path=path_a,
                    file_type=ta.value,
                    extracted_text=text_a,
                    label=label_a,
                )
                new_v = SimpleNamespace(
                    id=f"{cid}-new",
                    contract_id=cid,
                    file_path=path_b,
                    file_type=tb.value,
                    extracted_text=text_b,
                    label=label_b,
                )
                _run_full_compare(
                    base_v,
                    new_v,
                    cid,
                    label_a=label_a,
                    label_b=label_b,
                    path_a=path_a,
                    path_b=path_b,
                    text_a=text_a,
                    text_b=text_b,
                    mode=analysis_mode,
                )
                analysis_token = _compare_analysis_token(
                    "quick",
                    path_a=path_a,
                    path_b=path_b,
                    mode=analysis_mode,
                )
                set_compare_analysis_token(analysis_token)
                st.session_state.quick_compare_ctx = {
                    "kind": "quick",
                    "path_a": path_a,
                    "path_b": path_b,
                    "type_a": ta.value,
                    "type_b": tb.value,
                    "label_a": label_a,
                    "label_b": label_b,
                    "version_new": new_v,
                    "version_base": base_v,
                    "analysis_token": analysis_token,
                }
                st.session_state.compare_mode_kind = "quick"
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    ctx = st.session_state.get("quick_compare_ctx") or {}
    _show_compare_results(ctx)


def _diff_two_saved_versions() -> None:
    contract_id = render_contract_browse_selector("cmp_saved", sync_active=True)
    if not contract_id:
        st.stop()

    versions = db.get_versions(contract_id)
    if len(versions) < 2:
        st.info(
            "Este contrato precisa de pelo menos 2 versões. "
            "Use «Última versão salva × novo arquivo» para comparar com um PDF novo."
        )
        st.stop()

    va, vb = render_compare_version_pair(versions, base_key="base_ver", new_key="new_ver")

    n_base = count_comments_in_file(va.file_path)
    if n_base:
        st.caption(f"**{n_base}** comentário(s) na versão base.")
    elif count_comments_in_file(vb.file_path) == 0:
        st.warning("Nenhum comentário detectado na versão base.")

    analysis_mode = _analysis_mode_from_session()

    if st.button("Comparar versões", type="primary", key="cmp_run_saved"):
        if va.id == vb.id:
            st.warning("Selecione duas versões diferentes.")
        else:
            clear_compare_analysis_results()
            _run_full_compare(
                va,
                vb,
                contract_id,
                label_a=va.label,
                label_b=vb.label,
                path_a=va.file_path,
                path_b=vb.file_path,
                text_a=va.extracted_text,
                text_b=vb.extracted_text,
                save_version_id=vb.id,
                mode=analysis_mode,
            )
            analysis_token = _compare_analysis_token(
                "saved",
                version_a_id=va.id,
                version_b_id=vb.id,
                mode=analysis_mode,
            )
            set_compare_analysis_token(analysis_token)
            st.session_state.saved_compare_ctx = {
                "kind": "saved",
                "path_a": va.file_path,
                "path_b": vb.file_path,
                "type_a": va.file_type,
                "type_b": vb.file_type,
                "label_a": va.label,
                "label_b": vb.label,
                "version_new": vb,
                "version_base": va,
                "save_version_id": vb.id,
                "analysis_token": analysis_token,
            }
            st.session_state.compare_base_version_id = va.id
            st.session_state.compare_new_version_id = vb.id
            st.session_state.compare_mode_kind = "saved"
            st.rerun()

    ctx = st.session_state.get("saved_compare_ctx") or {}
    _show_compare_results(ctx)


_diff_section()
render_page_footer()
