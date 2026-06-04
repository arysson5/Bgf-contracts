"""Comparação contratual — diff entre versões e matriz Proposta x Contrato (PDF e DOCX)."""

import uuid
from types import SimpleNamespace

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import differ, extractor, matrix_analyzer
from app.db import database as db
from app.models.schemas import (
    ChangeRisk,
    CommentsReviewResult,
    ContractDiffResult,
    ContractualChange,
    MatrixItemStatus,
    ProposalContractMatrixResult,
)
from app.core.version_regression import analyze_version_regression
from app.utils.comments_ui import verify_comments_between_versions
from app.utils.inline_comments_ui import (
    mark_comment_queue_for_rebuild,
    render_inline_comments_workspace,
)
from app.utils.document_ui import render_document_navigator
from app.utils.matrix_ui import render_matrix_editor
from app.utils.settings import get_settings
from app.utils.theme import page_header, section_title, setup_page
from app.utils.data_cache import clear_data_cache
from app.utils.active_contract import (
    MODE_COMPARE_SAVED,
    MODE_MATRIX_SAVED,
    render_active_contract_banner,
    version_select_index,
)
from app.utils.ui import render_contract_selector, save_temp_upload

setup_page("Comparar Versões", page_icon="🔀")
settings = get_settings()

render_active_contract_banner(context="compare")

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}

STATUS_ICON = {
    MatrixItemStatus.CONFORME: "✅",
    MatrixItemStatus.DIVERGENTE: "⚠️",
    MatrixItemStatus.AUSENTE_CONTRATO: "➕",
    MatrixItemStatus.AUSENTE_PROPOSTA: "➖",
    MatrixItemStatus.OBRIGACAO_ADICIONAL: "📌",
}

STATUS_LABEL = {
    MatrixItemStatus.CONFORME: "Conforme",
    MatrixItemStatus.DIVERGENTE: "Divergente",
    MatrixItemStatus.AUSENTE_CONTRATO: "Ausente no contrato",
    MatrixItemStatus.AUSENTE_PROPOSTA: "Ausente na proposta",
    MatrixItemStatus.OBRIGACAO_ADICIONAL: "Obrigação adicional",
}


def _default_matrix_items() -> list[dict]:
    templates = db.get_matrix_templates()
    if not templates:
        return []
    items = db.get_matrix_items(templates[0].id)
    return [
        {
            "id": it.id,
            "categoria": it.categoria,
            "parametro_verificacao": it.parametro_verificacao,
            "risco_padrao": it.risco_padrao,
        }
        for it in items
    ]


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
    version_base=None,
    version_new=None,
    comment_verification: CommentsReviewResult | None = None,
    regression=None,
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

    if version_new and path_b:
        render_inline_comments_workspace(
            version_new,
            verification=comment_verification,
            regression=regression,
            key_prefix="cmp_diff_cmt",
            rebuild_queue=False,
        )


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


def _run_matrix(
    proposal_text: str,
    contract_text: str,
    matrix_items: list[dict],
    proposal_label: str,
    contract_label: str,
    proposal_path: str | None,
    contract_path: str | None,
    analysis_id: str,
) -> ProposalContractMatrixResult | None:
    try:
        with st.spinner("Analisando Proposta × Contrato com IA (pode levar alguns minutos)..."):
            return matrix_analyzer.analyze_matrix(
                proposal_text, contract_text, matrix_items, analysis_id,
                proposal_label=proposal_label, contract_label=contract_label,
                proposal_path=proposal_path, contract_path=contract_path,
            )
    except ValueError as exc:
        st.error(str(exc))
        return None
    except Exception as exc:
        logger.exception("Erro na análise da matriz")
        _show_analysis_error(exc)
        return None


def _render_matrix_results(
    result: ProposalContractMatrixResult,
    proposal_path: str | None,
    contract_path: str | None,
    proposal_type: str,
    contract_type: str,
    *,
    save_version_id: str | None = None,
    contract_version=None,
) -> None:
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Itens analisados", len(result.items))
    m2.metric("Divergências", result.divergences_count)
    m3.metric("Alto risco", result.high_risk_count)
    m4.metric("Obrigações adicionais", len(result.additional_obligations))

    section_title("Resumo executivo")
    st.info(result.executive_summary)

    tab_matrix, tab_alerts, tab_prop, tab_contract = st.tabs(
        ["Matriz de divergências", "Riscos e obrigações", "Proposta", "Contrato"]
    )

    with tab_matrix:
        for it in result.items:
            icon = STATUS_ICON.get(it.status, "•")
            risk_icon = RISK_ICON.get(it.risk_level, "")
            with st.expander(f"{icon} {it.categoria} — {STATUS_LABEL.get(it.status, it.status.value)} {risk_icon}"):
                st.caption(f"**Parâmetro:** {it.parametro_verificacao}")
                if it.divergencia:
                    st.write(f"**Divergência:** {it.divergencia}")
                if it.impacto:
                    st.write(f"**Impacto:** {it.impacto}")
                if it.recomendacao:
                    st.success(f"**Recomendação:** {it.recomendacao}")
                if it.contrato_evidencia:
                    st.markdown("**No contrato:**")
                    st.code(it.contrato_evidencia)
                if it.proposta_evidencia:
                    st.markdown("**Na proposta:**")
                    st.code(it.proposta_evidencia)

    with tab_alerts:
        if result.risk_alerts:
            st.markdown("**Alertas de risco**")
            for alert in result.risk_alerts:
                st.warning(alert)
        else:
            st.success("Nenhum alerta de risco material identificado.")
        if result.additional_obligations:
            st.markdown("**Obrigações adicionais (não previstas no contrato)**")
            for ob in result.additional_obligations:
                st.write(f"- {ob}")

    with tab_prop:
        locs = [loc for it in result.items for loc in it.locations_proposta]
        if proposal_path and locs:
            render_document_navigator(
                proposal_path, proposal_type, excerpt_locations=locs, key_prefix="mtx_prop"
            )
        else:
            st.info("Nenhum trecho localizado na proposta.")

    with tab_contract:
        locs = [loc for it in result.items for loc in it.locations_contrato]
        if contract_path and locs:
            render_document_navigator(
                contract_path, contract_type, excerpt_locations=locs, key_prefix="mtx_contract"
            )
        else:
            st.info("Nenhum trecho localizado no contrato.")

    if save_version_id and st.button("Salvar análise no contrato", key="save_matrix"):
        db.save_analysis_result(save_version_id, "matrix", result)
        clear_data_cache()
        st.success("Análise salva. Consulte em **Histórico de Análises**.")

    if contract_version and contract_path:
        render_inline_comments_workspace(
            contract_version,
            matrix_items=result.items,
            key_prefix="cmp_mtx_cmt",
            rebuild_queue=False,
        )


def _matrix_section() -> None:
    matrix_items = render_matrix_editor()

    if st.session_state.get("active_contract_id") and "matrix_mode" not in st.session_state:
        st.session_state.matrix_mode = MODE_MATRIX_SAVED
    mode = st.radio(
        "Modo",
        ["📎 Upload rápido (sem salvar)", "📁 Contrato salvo + proposta"],
        horizontal=True,
        key="matrix_mode",
    )

    if mode.startswith("📎"):
        section_title("Documentos")
        c1, c2 = st.columns(2)
        with c1:
            file_p = st.file_uploader("Proposta técnica/comercial", type=["pdf", "docx"], key="mtx_prop_file")
            label_p = st.text_input("Label proposta", value="Proposta", key="mtx_lp")
        with c2:
            file_c = st.file_uploader("Contrato assinado", type=["pdf", "docx"], key="mtx_contract_file")
            label_c = st.text_input("Label contrato", value="Contrato", key="mtx_lc")

        if st.button("Analisar Proposta × Contrato", type="primary", key="mtx_run_quick"):
            if not file_p or not file_c:
                st.warning("Envie a proposta e o contrato.")
            elif not matrix_items:
                st.warning("Configure ao menos um item na matriz.")
            else:
                try:
                    with st.spinner("Extraindo texto..."):
                        uid = uuid.uuid4().hex[:8]
                        path_p = save_temp_upload(file_p, settings.contracts_path, prefix="prop")
                        path_c = save_temp_upload(file_c, settings.contracts_path, prefix="contr")
                        text_p, tp = extractor.extract_text(path_p)
                        text_c, tc = extractor.extract_text(path_c)
                    result = _run_matrix(
                        text_p, text_c, matrix_items, label_p, label_c,
                        path_p, path_c, f"matrix-{uid}",
                    )
                    if result:
                        st.session_state.last_matrix_result = result
                        st.session_state.matrix_quick_ctx = {
                            "path_p": path_p, "path_c": path_c,
                            "type_p": tp.value, "type_c": tc.value,
                            "contract_version_id": f"matrix-{uid}-c",
                        }
                        st.session_state.matrix_mode_kind = "quick"
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get("matrix_mode_kind") == "quick" and st.session_state.get("last_matrix_result"):
            ctx = st.session_state.matrix_quick_ctx
            st.divider()
            contract_v = SimpleNamespace(
                id=ctx.get("contract_version_id", "mtx-quick-c"),
                contract_id=st.session_state.last_matrix_result.analysis_id,
                file_path=ctx["path_c"],
                file_type=ctx["type_c"],
            )
            _render_matrix_results(
                st.session_state.last_matrix_result,
                ctx["path_p"], ctx["path_c"], ctx["type_p"], ctx["type_c"],
                contract_version=contract_v,
            )
    else:
        contract_id = render_contract_selector("mtx_c")
        if not contract_id:
            st.stop()
        versions = db.get_versions(contract_id)
        if not versions:
            st.info("Este contrato ainda não tem versões. Faça upload na página de Checklist.")
            st.stop()
        labels = [f"v{v.version_number} — {v.label}" for v in versions]
        id_map = {lbl: v.id for lbl, v in zip(labels, versions)}
        mtx_idx = version_select_index(
            versions,
            st.session_state.get("active_version_id"),
            st.session_state.get("mtx_contract_ver_idx", len(versions) - 1),
        )
        sel = st.selectbox(
            "Versão do contrato (assinado)",
            labels,
            index=mtx_idx,
            key="mtx_contract_ver",
        )
        st.session_state.mtx_contract_ver_idx = labels.index(sel)
        contract_version = db.get_version(id_map[sel])
        contract_rec = db.get_contract(contract_id)
        use_stored_proposal = bool(
            contract_rec and db.contract_has_proposal(contract_rec)
        )
        text_p: str | None = None
        path_p: str | None = None
        type_p = "pdf"
        label_p = "Proposta"
        file_p = None

        if use_stored_proposal:
            st.success(
                f"Proposta do contrato ativo: **{contract_rec.proposal_label}** "
                f"({len(contract_rec.proposal_extracted_text):,} caracteres)"
            )
            text_p = contract_rec.proposal_extracted_text
            path_p = contract_rec.proposal_file_path
            label_p = contract_rec.proposal_label or "Proposta"
            type_p = contract_rec.proposal_file_type or "pdf"
        else:
            file_p = st.file_uploader(
                "Proposta técnica/comercial",
                type=["pdf", "docx"],
                key="mtx_prop_saved",
            )
            label_p = st.text_input("Label proposta", value="Proposta", key="mtx_lp_saved")

        if st.button("Analisar Proposta × Contrato", type="primary", key="mtx_run_saved"):
            if not use_stored_proposal and not file_p:
                st.warning("Envie a proposta ou cadastre-a em Upload (seção 1b).")
            elif not matrix_items:
                st.warning("Configure ao menos um item na matriz.")
            else:
                try:
                    if not use_stored_proposal:
                        with st.spinner("Extraindo texto..."):
                            path_p = save_temp_upload(file_p, settings.contracts_path, prefix="prop")
                            text_p, tp_doc = extractor.extract_text(path_p)
                            type_p = tp_doc.value
                    result = _run_matrix(
                        text_p,
                        contract_version.extracted_text,
                        matrix_items,
                        label_p,
                        contract_version.label,
                        path_p,
                        contract_version.file_path,
                        contract_id,
                    )
                    if result:
                        st.session_state.last_matrix_result = result
                        st.session_state.matrix_saved_ctx = {
                            "path_p": path_p, "path_c": contract_version.file_path,
                            "type_p": type_p, "type_c": contract_version.file_type,
                            "save_version_id": contract_version.id,
                        }
                        st.session_state.matrix_mode_kind = "saved"
                        mark_comment_queue_for_rebuild(
                            contract_version.id, "cmp_mtx_cmt"
                        )
                except ValueError as exc:
                    st.error(str(exc))

        if st.session_state.get("matrix_mode_kind") == "saved" and st.session_state.get("last_matrix_result"):
            ctx = st.session_state.matrix_saved_ctx
            st.divider()
            _render_matrix_results(
                st.session_state.last_matrix_result,
                ctx["path_p"], ctx["path_c"], ctx["type_p"], ctx["type_c"],
                save_version_id=ctx["save_version_id"],
                contract_version=db.get_version(ctx["save_version_id"]),
            )


def _diff_section() -> None:
    if st.session_state.get("active_contract_id") and "compare_mode" not in st.session_state:
        st.session_state.compare_mode = MODE_COMPARE_SAVED
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
                    cid = f"quick-{uid}"
                    result = _run_compare(text_a, text_b, label_a, label_b, path_a, path_b, cid)
                    if result:
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
                        with st.spinner("Verificando comentários da versão base..."):
                            verification = verify_comments_between_versions(
                                base_v, new_v, cid, result
                            )
                        st.session_state.last_diff_result = result
                        st.session_state.last_comment_verification = verification
                        st.session_state.quick_compare_ctx = {
                            "path_a": path_a, "path_b": path_b,
                            "type_a": ta.value, "type_b": tb.value,
                            "label_a": label_a, "label_b": label_b,
                            "contract_id": cid,
                            "version_new": new_v,
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
                version_new=ctx.get("version_new"),
                comment_verification=st.session_state.get("last_comment_verification"),
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
        base_idx = version_select_index(
            versions,
            st.session_state.get("compare_base_version_id"),
            st.session_state.get("compare_base_idx", 0),
        )
        new_idx = version_select_index(
            versions,
            st.session_state.get("compare_new_version_id"),
            st.session_state.get("compare_new_idx", min(1, len(labels) - 1)),
        )
        c1, c2 = st.columns(2)
        with c1:
            bl = st.selectbox("Versão base (padrão: anterior)", labels, base_idx, key="base_ver")
        with c2:
            nl = st.selectbox("Versão nova (padrão: última)", labels, new_idx, key="new_ver")
        st.session_state.compare_base_idx = labels.index(bl)
        st.session_state.compare_new_idx = labels.index(nl)
        st.session_state.compare_base_version_id = id_map[bl]
        st.session_state.compare_new_version_id = id_map[nl]
        va, vb = db.get_version(id_map[bl]), db.get_version(id_map[nl])
        contract_rec = db.get_contract(contract_id)
        if contract_rec and db.contract_has_proposal(contract_rec):
            st.caption(
                f"Proposta de referência: **{contract_rec.proposal_label}** "
                "(usada na detecção de regressões na 2ª revisão)."
            )
        else:
            st.warning(
                "Cadastre a proposta em **Upload & Análise inicial** (seção 1b) "
                "para detectar retiradas que prejudiquem a negociação."
            )

        if st.button("Analisar contratos", type="primary"):
            if va.id == vb.id:
                st.warning("Selecione versões diferentes.")
            else:
                result = _run_compare(
                    va.extracted_text, vb.extracted_text, va.label, vb.label,
                    va.file_path, vb.file_path, contract_id,
                )
                if result:
                    contract_rec = db.get_contract(contract_id)
                    with st.spinner("Verificando comentários da versão base..."):
                        verification = verify_comments_between_versions(
                            va, vb, contract_id, result
                        )
                    regression = None
                    if contract_rec and db.contract_has_proposal(contract_rec):
                        with st.spinner("Detectando regressões vs proposta e matriz..."):
                            regression = analyze_version_regression(
                                va.extracted_text,
                                vb.extracted_text,
                                contract_rec.proposal_extracted_text,
                                _default_matrix_items(),
                                result,
                                contract_id,
                                label_base=va.label,
                                label_new=vb.label,
                                proposal_label=contract_rec.proposal_label,
                            )
                    st.session_state.last_diff_result = result
                    st.session_state.last_comment_verification = verification
                    st.session_state.last_regression_result = regression
                    st.session_state.compare_base_version_id = va.id
                    st.session_state.compare_new_version_id = vb.id
                    st.session_state.compare_mode_kind = "saved"
                    mark_comment_queue_for_rebuild(vb.id, "cmp_diff_cmt")

        if st.session_state.get("compare_mode_kind") == "saved" and st.session_state.last_diff_result:
            va = db.get_version(st.session_state.compare_base_version_id)
            vb = db.get_version(st.session_state.compare_new_version_id)
            if va and vb:
                st.divider()
                _render_contractual_results(
                    st.session_state.last_diff_result,
                    va.file_path, vb.file_path, va.file_type, vb.file_type,
                    va.label, vb.label,
                    save_version_id=vb.id,
                    version_base=va,
                    version_new=vb,
                    comment_verification=st.session_state.get("last_comment_verification"),
                    regression=st.session_state.get("last_regression_result"),
                )


# --- Dispatcher da página ---

page_header(
    "Comparar & Analisar",
    "Diff entre versões com verificação de comentários, ou matriz Proposta × Contrato com sugestões de revisão.",
)

analysis_kind = st.radio(
    "Tipo de análise",
    ["🔀 Comparar versões (diff)", "🧩 Proposta × Contrato (matriz)"],
    horizontal=True,
    key="analysis_kind",
)

if analysis_kind.startswith("🔀"):
    _diff_section()
else:
    _matrix_section()
