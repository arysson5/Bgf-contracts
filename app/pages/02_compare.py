"""Comparação contratual entre versões — PDF e DOCX."""

import uuid

import streamlit as st
from loguru import logger

from app.core import differ, extractor
from app.db import database as db
from app.models.schemas import ChangeRisk, ContractDiffResult, ContractualChange
from app.utils.document_ui import render_document_navigator
from app.utils.settings import get_settings
from app.utils.theme import page_header, section_title, setup_page
from app.utils.data_cache import clear_data_cache
from app.utils.ui import render_contract_selector, save_temp_upload

setup_page("Comparar Versões", page_icon="🔀")
settings = get_settings()

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
) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Alterações materiais", result.material_changes_count)
    m2.metric("Alto risco", result.high_risk_count)
    m3.metric("Total de alterações", len(result.contractual_changes))
    m4.metric("Exige atenção", "Sim" if result.has_significant_changes else "Não")

    section_title("Resumo executivo")
    st.info(result.executive_summary)
    if result.recommendation:
        section_title("Recomendação")
        st.success(result.recommendation)

    tab_changes, tab_doc_new, tab_doc_base = st.tabs(
        [
            "Alterações contratuais",
            f"Documento — {label_b}",
            f"Documento — {label_a}",
        ]
    )

    with tab_changes:
        for ch in result.contractual_changes:
            icon = RISK_ICON.get(ch.risk_level, "•")
            attn = " ⚠️" if ch.requires_attention else ""
            with st.expander(f"{icon} {ch.clause_reference} — {ch.title}{attn}"):
                st.write(ch.description)
                st.caption(f"**Categoria:** {ch.category.value} | **Risco:** {ch.risk_level.value} | **Parte:** {ch.affected_party}")
                st.write(f"**Impacto jurídico:** {ch.legal_impact}")
                if ch.original_text:
                    st.markdown("**Texto original:**")
                    st.code(ch.original_text[:2000])
                if ch.new_text:
                    st.markdown("**Texto novo:**")
                    st.code(ch.new_text[:2000])

    with tab_doc_new:
        if path_b:
            st.caption(f"Navegue pelas alterações na versão nova ({type_b.upper()})")
            render_document_navigator(
                path_b, type_b, result.contractual_changes, version_side="new", key_prefix="cmp_new"
            )
        else:
            st.warning("Arquivo da versão nova não disponível.")

    with tab_doc_base:
        if path_a:
            st.caption(f"Trechos alterados ou removidos na versão base ({type_a.upper()})")
            render_document_navigator(
                path_a, type_a, result.contractual_changes, version_side="base", key_prefix="cmp_base"
            )
        else:
            st.warning("Arquivo da versão base não disponível.")

    if save_version_id and st.button("Salvar análise no contrato", key="save_contractual"):
        db.save_analysis_result(save_version_id, "diff", result)
        clear_data_cache()
        st.success("Análise salva. Consulte em **Histórico de Análises**.")


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
        with st.spinner("Análise contratual criteriosa com IA (pode levar alguns minutos)..."):
            return differ.compare_versions(
                text_a, text_b, label_a, label_b, contract_id, path_a=path_a, path_b=path_b
            )
    except ValueError as exc:
        st.error(str(exc))
        return None
    except Exception as exc:
        logger.exception("Erro na análise contratual")
        st.warning(f"Erro na API: {exc}. Tente novamente.")
        return None


page_header(
    "Comparar Versões",
    "Análise contratual criteriosa entre duas versões (PDF ou DOCX) — não é comparador de texto.",
)

mode = st.radio(
    "Modo",
    ["📎 Upload rápido (sem salvar)", "📁 Contrato salvo"],
    horizontal=True,
    key="compare_mode",
)

if mode.startswith("📎"):
    section_title("Upload rápido")
    c1, c2 = st.columns(2)
    with c1:
        file_a = st.file_uploader("Contrato base", type=["pdf", "docx"], key="quick_a")
        label_a = st.text_input("Label base", value="Original", key="ql_a")
    with c2:
        file_b = st.file_uploader("Contrato novo", type=["pdf", "docx"], key="quick_b")
        label_b = st.text_input("Label novo", value="Versão Cliente", key="ql_b")

    if st.button("Analisar contratos", type="primary"):
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
                result = _run_compare(text_a, text_b, label_a, label_b, path_a, path_b, f"quick-{uid}")
                if result:
                    st.session_state.last_diff_result = result
                    st.session_state.quick_compare_ctx = {
                        "path_a": path_a, "path_b": path_b,
                        "type_a": ta.value, "type_b": tb.value,
                        "label_a": label_a, "label_b": label_b,
                    }
                    st.session_state.compare_mode_kind = "quick"
            except ValueError as exc:
                st.error(str(exc))

    if st.session_state.get("compare_mode_kind") == "quick" and st.session_state.last_diff_result:
        ctx = st.session_state.quick_compare_ctx
        st.divider()
        _render_contractual_results(
            st.session_state.last_diff_result,
            ctx["path_a"], ctx["path_b"], ctx["type_a"], ctx["type_b"],
            ctx["label_a"], ctx["label_b"],
        )
else:
    contract_id = render_contract_selector("cmp_c")
    if not contract_id:
        st.stop()
    versions = db.get_versions(contract_id)
    if not versions:
        st.stop()

    labels = [f"v{v.version_number} — {v.label}" for v in versions]
    id_map = {lbl: v.id for lbl, v in zip(labels, versions)}
    c1, c2 = st.columns(2)
    with c1:
        bl = st.selectbox("Versão base", labels, 0, key="base_ver")
    with c2:
        nl = st.selectbox("Versão nova", labels, min(1, len(labels) - 1), key="new_ver")
    va, vb = db.get_version(id_map[bl]), db.get_version(id_map[nl])

    if st.button("Analisar contratos", type="primary"):
        if va.id == vb.id:
            st.warning("Selecione versões diferentes.")
        else:
            result = _run_compare(
                va.extracted_text, vb.extracted_text, va.label, vb.label,
                va.file_path, vb.file_path, contract_id,
            )
            if result:
                st.session_state.last_diff_result = result
                st.session_state.compare_base_version_id = va.id
                st.session_state.compare_new_version_id = vb.id
                st.session_state.compare_mode_kind = "saved"

    if st.session_state.get("compare_mode_kind") == "saved" and st.session_state.last_diff_result:
        va = db.get_version(st.session_state.compare_base_version_id)
        vb = db.get_version(st.session_state.compare_new_version_id)
        if va and vb:
            st.divider()
            _render_contractual_results(
                st.session_state.last_diff_result,
                va.file_path, vb.file_path, va.file_type, vb.file_type,
                va.label, vb.label, save_version_id=vb.id,
            )
