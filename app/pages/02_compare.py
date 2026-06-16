"""Comparação contratual entre versões — comentários atendidos e alterações no contrato."""

import uuid
from pathlib import Path
from types import SimpleNamespace

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import differ, extractor
from app.db import database as db
from app.models.schemas import (
    ChangeRisk,
    CommentsReviewResult,
    ContractDiffResult,
)
from app.utils.comments_ui import (
    count_comments_in_file,
    render_comment_verification_results,
    verify_comments_between_versions,
)
from app.utils.document_ui import render_document_navigator
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
    "Contrato com comentários × versão revisada do cliente. "
    "Verifique pedidos atendidos e alterações no texto.",
)

render_active_contract_banner(context="compare")

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}


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
    comment_verification: CommentsReviewResult | None = None,
) -> None:
    section_title("Resultado")

    tab_comments, tab_diff, tab_doc_new, tab_doc_base = st.tabs(
        [
            "Comentários",
            "Alterações no contrato",
            f"📄 {label_b}",
            f"📄 {label_a}",
        ]
    )

    with tab_comments:
        if comment_verification:
            render_comment_verification_results(
                comment_verification,
                new_version=version_new,
                key_prefix="cmp_cmt_ver",
            )
        else:
            st.info("Verificação de comentários não disponível.")

    with tab_diff:
        c1, c2, c3 = st.columns(3)
        c1.metric("Alterações materiais", result.material_changes_count)
        c2.metric("Alto risco", result.high_risk_count)
        c3.metric("Exige atenção", "Sim" if result.has_significant_changes else "Não")
        if result.executive_summary:
            st.info(result.executive_summary)
        if result.recommendation:
            st.success(result.recommendation)
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

    with tab_doc_new:
        if path_b:
            render_document_navigator(
                path_b, type_b, result.contractual_changes, version_side="new", key_prefix="cmp_new"
            )
        else:
            st.warning("Arquivo da versão revisada não disponível.")

    with tab_doc_base:
        if path_a:
            render_document_navigator(
                path_a, type_a, result.contractual_changes, version_side="base", key_prefix="cmp_base"
            )
        else:
            st.warning("Arquivo do contrato com comentários não disponível.")

    if save_version_id and st.button("Salvar análise", key="save_contractual"):
        db.save_analysis_result(save_version_id, "diff", result)
        if comment_verification:
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
) -> ContractDiffResult | None:
    try:
        with st.spinner("Analisando diferenças entre as versões..."):
            return differ.compare_versions(
                text_a, text_b, label_a, label_b, contract_id, path_a=path_a, path_b=path_b
            )
    except ValueError as exc:
        st.error(str(exc))
        return None
    except Exception as exc:
        logger.exception("Erro na análise contratual")
        _show_analysis_error(exc)
        return None


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
) -> None:
    """Diff contratual + verificação de comentários."""
    result = _run_compare(text_a, text_b, label_a, label_b, path_a, path_b, contract_id)
    if not result:
        return

    with st.spinner("Verificando comentários..."):
        verification = verify_comments_between_versions(base_v, new_v, contract_id, result)

    st.session_state.last_diff_result = result
    st.session_state.last_comment_verification = verification
    st.session_state.last_regression_result = None


def _show_compare_results(ctx: dict) -> None:
    if st.session_state.get("compare_mode_kind") != ctx.get("kind"):
        return
    if not st.session_state.get("last_diff_result"):
        return
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
        comment_verification=st.session_state.get("last_comment_verification"),
    )


def _diff_section() -> None:
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
    """Última versão salva no contrato × arquivo novo enviado pelo usuário."""
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

    if st.button("Comparar versões", type="primary", key="cmp_run_hybrid"):
        if not file_b:
            st.warning("Envie o arquivo da versão revisada.")
        else:
            try:
                with st.spinner("Extraindo texto..."):
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
                )
                st.session_state.hybrid_compare_ctx = {
                    "kind": "hybrid",
                    "path_a": va.file_path,
                    "path_b": path_b,
                    "type_a": va.file_type,
                    "type_b": tb.value,
                    "label_a": va.label,
                    "label_b": label_b,
                    "version_new": new_v,
                    "save_version_id": save_vid,
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

    if st.button("Comparar versões", type="primary", key="cmp_run_quick"):
        if not file_a or not file_b:
            st.warning("Envie os dois arquivos.")
        else:
            try:
                with st.spinner("Extraindo texto..."):
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
                )
                st.session_state.quick_compare_ctx = {
                    "kind": "quick",
                    "path_a": path_a,
                    "path_b": path_b,
                    "type_a": ta.value,
                    "type_b": tb.value,
                    "label_a": label_a,
                    "label_b": label_b,
                    "version_new": new_v,
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

    if st.button("Comparar versões", type="primary", key="cmp_run_saved"):
        if va.id == vb.id:
            st.warning("Selecione duas versões diferentes.")
        else:
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
            )
            st.session_state.saved_compare_ctx = {
                "kind": "saved",
                "path_a": va.file_path,
                "path_b": vb.file_path,
                "type_a": va.file_type,
                "type_b": vb.file_type,
                "label_a": va.label,
                "label_b": vb.label,
                "version_new": vb,
                "save_version_id": vb.id,
            }
            st.session_state.compare_base_version_id = va.id
            st.session_state.compare_new_version_id = vb.id
            st.session_state.compare_mode_kind = "saved"
            st.rerun()

    ctx = st.session_state.get("saved_compare_ctx") or {}
    _show_compare_results(ctx)


_diff_section()
render_page_footer()
