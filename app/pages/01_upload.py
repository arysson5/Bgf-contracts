"""Upload de contrato + análise inicial pela matriz de parâmetros."""

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import extractor, matrix_checker
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import ChangeRisk, ContractMatrixInitialResult, MatrixParameterCheck
from app.utils.helpers import count_tokens
from app.utils.document_ui import render_document_navigator
from app.utils.inline_comments_ui import (
    mark_comment_queue_for_rebuild,
    render_inline_comments_workspace,
)
from app.utils.matrix_ui import render_matrix_editor
from app.utils.settings import get_settings
from app.utils.data_cache import clear_data_cache
from app.utils.theme import page_header, render_page_footer, section_title, setup_page
from app.utils.active_contract import (
    contract_identity_matches,
    get_active_contract,
    init_upload_version_label_widget,
    render_active_contract_banner,
    resolve_contract_for_upload,
)
from app.utils.analysis_session import (
    clear_matrix_initial_analysis_results,
    matrix_analysis_matches_version,
    set_matrix_analysis_token,
)
from app.utils.ui import save_uploaded_file

setup_page("Upload & Análise")
settings = get_settings()

page_header(
    "Upload & Análise inicial",
    "Envie o contrato, configure a matriz e analise escopo, prazos e condições com IA.",
)

render_active_contract_banner(context="upload")

init_upload_version_label_widget()

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}


def _render_matrix_check(check: MatrixParameterCheck) -> None:
    icon = "✅" if check.present else "❌"
    risk = RISK_ICON.get(check.risk_level, "")
    with st.expander(f"{icon} {check.categoria} {risk}", expanded=not check.present):
        st.caption(check.parametro_verificacao)
        st.write(check.observation)
        if check.found_excerpt:
            st.code(check.found_excerpt)
        if check.proposal_excerpt:
            st.caption("Na proposta:")
            st.code(check.proposal_excerpt)
        if check.aligns_with_proposal is False:
            st.warning("Desalinhado com a proposta.")


def _render_matrix_summary(result: ContractMatrixInitialResult) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Atendidos", f"{result.items_met}/{result.total_items}")
    c2.metric("Score", f"{result.overall_score:.0%}")
    c3.metric("Alertas", len(result.risk_alerts))
    if result.executive_summary:
        st.info(result.executive_summary)
    if result.risk_alerts:
        for alert in result.risk_alerts:
            st.warning(alert)
    if result.critical_gaps:
        st.error("Lacunas críticas:\n- " + "\n- ".join(result.critical_gaps))


def _render_contract_upload() -> None:
    uploaded = st.file_uploader(
        "Arquivo (PDF ou DOCX)",
        type=["pdf", "docx"],
        key="upload_contract_file",
    )
    col1, col2, col3 = st.columns(3)
    with col1:
        contract_name = st.text_input("Nome do contrato", key="upload_contract_name")
    with col2:
        client_name = st.text_input("Nome do cliente", key="upload_client_name")
    with col3:
        version_label = st.text_input("Label da versão", key="upload_version_label")

    active_rec = get_active_contract()
    if active_rec and contract_name and client_name:
        if not contract_identity_matches(contract_name, client_name, active_rec):
            st.caption("Será criado um **novo contrato** (nome ou cliente diferente do ativo).")

    if uploaded and contract_name and client_name:
        if st.button("Salvar contrato", type="primary", key="upload_save_contract"):
            try:
                with st.spinner("Extraindo texto..."):
                    path = save_uploaded_file(uploaded, settings.contracts_path)
                    text, doc_type = extractor.extract_text(path)

                contract_id, created_new = resolve_contract_for_upload(contract_name, client_name)

                version = db.add_version(
                    contract_id, version_label, path, doc_type, text
                )
                clear_data_cache()
                st.session_state.active_version_id = version.id
                st.session_state.upload_version_id = version.id
                st.session_state["upload_version_label_default"] = (
                    f"Revisão v{version.version_number + 1}"
                )
                if created_new:
                    st.success(
                        f"Contrato **{contract_name}** criado — v{version.version_number} salva."
                    )
                else:
                    st.success(f"Versão v{version.version_number} salva.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
            except Exception as exc:
                logger.exception("Erro no upload")
                msg = str(exc)
                if "session_state" in msg and "upload_version_label" in msg:
                    st.error(
                        "Conflito interno do formulário. Atualize a página (F5) e tente novamente."
                    )
                elif "getvalue" in msg.lower() or "uploadedfile" in msg.lower():
                    st.error(
                        "Arquivo não disponível. Selecione o PDF/DOCX novamente e clique em Salvar."
                    )
                else:
                    st.error(f"Arquivo corrompido ou ilegível: {exc}")


def _render_proposal_upload() -> None:
    proposal_contract_id = st.session_state.get("active_contract_id")
    version_id_local = st.session_state.get("upload_version_id")
    if not proposal_contract_id and version_id_local:
        ver_tmp = db.get_version(version_id_local)
        if ver_tmp:
            proposal_contract_id = ver_tmp.contract_id
    if not proposal_contract_id:
        return

    contract_rec = db.get_contract(proposal_contract_id)
    has_proposal = contract_rec and db.contract_has_proposal(contract_rec)
    if has_proposal:
        st.caption(f"Proposta cadastrada: **{contract_rec.proposal_label}**")
        if contract_rec.proposal_file_path:
            with open(contract_rec.proposal_file_path, "rb") as pf:
                st.download_button(
                    "Baixar proposta",
                    pf.read(),
                    file_name=Path(contract_rec.proposal_file_path).name,
                    key=f"dl_proposal_{proposal_contract_id}",
                )
    else:
        st.caption("Nenhuma proposta cadastrada — análise somente com a matriz.")

    prop_file = st.file_uploader(
        "Enviar proposta (PDF ou DOCX)" if not has_proposal else "Atualizar proposta",
        type=["pdf", "docx"],
        key=f"upload_proposal_file_{proposal_contract_id}",
    )
    prop_label = st.text_input(
        "Label da proposta",
        value=contract_rec.proposal_label if contract_rec and contract_rec.proposal_label else "Proposta comercial",
        key=f"upload_proposal_label_{proposal_contract_id}",
    )
    if prop_file and st.button("Salvar proposta", key=f"save_proposal_{proposal_contract_id}"):
        try:
            with st.spinner("Extraindo proposta..."):
                ppath = save_uploaded_file(prop_file, settings.contracts_path)
                ptext, ptype = extractor.extract_text(ppath)
            db.set_contract_proposal(
                proposal_contract_id,
                ppath,
                ptype.value,
                ptext,
                prop_label,
            )
            clear_data_cache()
            st.success("Proposta salva.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))


def _render_matrix_section() -> list[dict]:
    return render_matrix_editor(
        section_label="Parâmetros de verificação",
        template_key="upload_matrix_template_choice",
        new_name_key="upload_matrix_new_name",
        new_rows_key="upload_matrix_new_rows",
        new_editor_key="upload_matrix_new_editor",
        save_new_key="upload_matrix_save_new",
    )


def _load_matrix_items() -> list[dict]:
    items = _render_matrix_section()
    if items:
        st.session_state["_upload_matrix_items"] = items
        return items
    return st.session_state.get("_upload_matrix_items", [])


section_title("1. Contrato")

_render_contract_upload()

version_id = st.session_state.get("upload_version_id")

if version_id:
    ver_active = db.get_version(version_id)
    if ver_active:
        st.caption(f"Versão ativa: **v{ver_active.version_number}** — {ver_active.label}")
elif st.session_state.get("active_contract_id"):
    st.warning("Envie o primeiro PDF/DOCX ou escolha outro contrato na sidebar.")

section_title("2. Proposta comercial (opcional)")
st.caption("Vinculada a este contrato. Sem proposta, a análise usa apenas a matriz no texto do contrato.")

_render_proposal_upload()
if not st.session_state.get("active_contract_id") and not st.session_state.get("upload_version_id"):
    st.caption("Salve uma versão do contrato para vincular a proposta.")

section_title("3. Matriz de parâmetros")
matrix_items = _load_matrix_items()

section_title("4. Analisar")
can_analyze = bool(version_id) and len(matrix_items) > 0

if can_analyze:
    ver = db.get_version(version_id)
    if ver:
        token_est = count_tokens(ver.extracted_text)
        if token_est > 50000:
            st.warning(f"Contrato grande (~{token_est:,} tokens) — análise pode levar vários minutos.")

if st.button("Analisar contrato", type="primary", disabled=not can_analyze):
    clear_matrix_initial_analysis_results()
    ver = db.get_version(version_id)
    try:
        contract_rec = db.get_contract(ver.contract_id)
        proposal_text = ""
        proposal_label = "Proposta comercial"
        if contract_rec and db.contract_has_proposal(contract_rec):
            proposal_text = contract_rec.proposal_extracted_text or ""
            proposal_label = contract_rec.proposal_label or "Proposta comercial"

        total_items = len(matrix_items)
        section_title("Resultado")
        st.caption(f"Analisando **{total_items}** parâmetros — cada tópico aparece assim que ficar pronto.")

        progress_bar = st.progress(0.0, text="Iniciando...")
        status = st.empty()
        metrics_ph = st.empty()
        checks_ph = st.empty()
        completed: list[MatrixParameterCheck] = []

        def _on_progress(current: int, total: int, label: str) -> None:
            pct = (current - 1) / total if total else 0.0
            progress_bar.progress(
                max(0.0, pct),
                text=f"Analisando {current}/{total}…",
            )
            status.caption(f"Em análise: **{label}**")

        def _on_item_done(check: MatrixParameterCheck, current: int, total: int) -> None:
            if check.found_excerpt:
                check.locations = find_in_document(ver.file_path, check.found_excerpt)
            completed.append(check)
            met = sum(1 for c in completed if c.present)
            progress_bar.progress(
                current / total if total else 1.0,
                text=f"{current}/{total} prontos",
            )
            status.success(f"Pronto ({current}/{total}): **{check.categoria}**")
            with metrics_ph.container():
                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Atendidos", f"{met}/{total}")
                mc2.metric("Concluídos", f"{current}/{total}")
                mc3.metric("Pendentes", total - current)
            with checks_ph.container():
                st.markdown("**Parâmetros verificados**")
                for i, done in enumerate(completed):
                    _render_matrix_check(done)

        result = matrix_checker.check_matrix_against_contract(
            ver.extracted_text,
            matrix_items,
            ver.contract_id,
            proposal_text=proposal_text or None,
            proposal_label=proposal_label,
            progress_callback=_on_progress,
            item_complete_callback=_on_item_done,
        )

        progress_bar.progress(1.0, text="Análise concluída.")
        status.empty()

        db.save_analysis_result(version_id, "matrix_initial", result)
        clear_data_cache()
        st.session_state.last_matrix_initial_result = result
        st.session_state.checklist_version_id = version_id
        set_matrix_analysis_token(version_id)
        st.session_state.matrix_analysis_saved = True
        mark_comment_queue_for_rebuild(version_id, "upload_mtx")
        st.success("Análise concluída e salva no **Histórico**.")
        st.rerun()
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        logger.exception("Erro na análise")
        st.warning(f"Erro na análise: {exc}. Tente novamente.")

matrix_result: ContractMatrixInitialResult | None = None
if matrix_analysis_matches_version(version_id):
    matrix_result = st.session_state.get("last_matrix_initial_result")
if matrix_result:
    section_title("Resultado")
    if st.session_state.pop("matrix_analysis_saved", False):
        st.caption("Última análise salva automaticamente no Histórico.")
    _render_matrix_summary(matrix_result)

    ver = db.get_version(st.session_state.get("checklist_version_id") or version_id)
    tab_res, tab_doc = st.tabs(["Parâmetros", "Documento"])
    with tab_res:
        for i, check in enumerate(matrix_result.checks):
            _render_matrix_check(check)

    with tab_doc:
        if ver:
            all_locs = [loc for check in matrix_result.checks for loc in check.locations]
            if all_locs:
                render_document_navigator(
                    ver.file_path, ver.file_type, excerpt_locations=all_locs, key_prefix="mtx_ini"
                )
            else:
                st.info("Nenhum trecho localizado no documento.")

    if ver:
        render_inline_comments_workspace(
            ver,
            matrix_checks=matrix_result.checks,
            key_prefix="upload_mtx",
            rebuild_queue=False,
        )

elif not can_analyze:
    st.caption("Salve o contrato e configure ao menos um parâmetro na matriz.")

render_page_footer()
