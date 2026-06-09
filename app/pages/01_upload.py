"""Upload de contrato + análise inicial (requisitos ou parâmetros de verificação)."""

from pathlib import Path

import streamlit as st

from app.utils.dev_reload import sync_app_modules

sync_app_modules(st.session_state)

from loguru import logger

from app.core import checker, extractor, matrix_checker
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import ChangeRisk, ContractChecklistResult, ContractMatrixInitialResult
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
    render_active_contract_banner,
    resolve_contract_for_upload,
)
from app.utils.ui import save_uploaded_file

setup_page("Upload & Checklist", page_icon="📤")
settings = get_settings()

page_header(
    "Upload & Análise inicial",
    "Cada cliente/contrato tem proposta própria (opcional). Sem proposta, a análise usa só a matriz no contrato.",
)

render_active_contract_banner(context="upload")

RISK_ICON = {ChangeRisk.HIGH: "🔴", ChangeRisk.MEDIUM: "🟡", ChangeRisk.LOW: "🟢"}

section_title("1. Upload do contrato")
uploaded = st.file_uploader("Arquivo (PDF ou DOCX)", type=["pdf", "docx"])
col1, col2, col3 = st.columns(3)
with col1:
    contract_name = st.text_input(
        "Nome do contrato",
        key="upload_contract_name",
    )
with col2:
    client_name = st.text_input(
        "Nome do cliente",
        key="upload_client_name",
    )
with col3:
    if "upload_version_label" not in st.session_state:
        st.session_state["upload_version_label"] = st.session_state.get(
            "upload_version_label_default", "Original"
        )
    version_label = st.text_input("Label da versão", key="upload_version_label")

active_rec = get_active_contract()
if active_rec and contract_name and client_name:
    if not contract_identity_matches(contract_name, client_name, active_rec):
        st.info(
            "Nome ou cliente **diferentes** do contrato ativo na sidebar — "
            "ao salvar, será criado um **novo contrato** (proposta própria, sem herdar a anterior)."
        )
    else:
        st.caption(
            "Mesmo contrato ativo: novas versões serão vinculadas a ele; "
            "a proposta cadastrada na seção 1b vale só para este contrato."
        )
elif st.session_state.get("active_contract_id"):
    st.caption(
        "Preencha nome do contrato e do cliente. Versões iguais ao contrato ativo "
        "são vinculadas a ele; nomes diferentes criam um novo contrato."
    )

version_id = st.session_state.get("upload_version_id")

if uploaded and contract_name and client_name:
    if st.button("Salvar contrato e versão", type="primary"):
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
            version_id = version.id
            if created_new:
                st.success(
                    f"Novo contrato **{contract_name}** ({client_name}) criado. "
                    f"Versão '{version_label}' salva. Cadastre a proposta na seção 1b (opcional)."
                )
            else:
                st.success(f"Versão '{version_label}' salva com sucesso.")
            with st.expander("Preview do texto extraído"):
                st.text(text[:500] + ("..." if len(text) > 500 else ""))
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            logger.exception("Erro no upload")
            st.error(f"Arquivo corrompido ou ilegível: {exc}")

if version_id:
    ver_active = db.get_version(version_id)
    if ver_active:
        st.success(
            f"Versão pronta para análise: **v{ver_active.version_number}** — {ver_active.label} "
            f"(`{ver_active.id[:8]}…`)"
        )
    else:
        st.info(f"Versão ativa para análise: `{version_id[:8]}...`")
elif st.session_state.get("active_contract_id"):
    st.warning(
        "Contrato ativo sem versões salvas. Envie o primeiro PDF/DOCX abaixo "
        "ou escolha outro contrato na sidebar."
    )

# --- Proposta comercial (persistente no contrato) ---
section_title("1b. Proposta comercial (opcional)")
st.caption(
    "A proposta fica vinculada **somente a este contrato**. "
    "Se não enviar proposta, a análise inicial usará **apenas a matriz** no texto do contrato."
)
proposal_contract_id = st.session_state.get("active_contract_id")
if not proposal_contract_id and version_id:
    ver_tmp = db.get_version(version_id)
    if ver_tmp:
        proposal_contract_id = ver_tmp.contract_id

if proposal_contract_id:
    contract_rec = db.get_contract(proposal_contract_id)
    has_proposal = contract_rec and db.contract_has_proposal(contract_rec)
    if has_proposal:
        st.success(
            f"Proposta cadastrada: **{contract_rec.proposal_label}** "
            f"({len(contract_rec.proposal_extracted_text):,} caracteres extraídos)"
        )
        if contract_rec.proposal_file_path:
            with open(contract_rec.proposal_file_path, "rb") as pf:
                st.download_button(
                    "⬇️ Baixar proposta",
                    pf.read(),
                    file_name=Path(contract_rec.proposal_file_path).name,
                    key=f"dl_proposal_{proposal_contract_id}",
                )
    else:
        st.info(
            "Nenhuma proposta para este contrato — a análise usará só a matriz. "
            "Envie abaixo se quiser comparar contrato × proposta."
        )

    prop_file = st.file_uploader(
        "Enviar proposta (PDF ou DOCX)" if not has_proposal else "Atualizar proposta (PDF ou DOCX)",
        type=["pdf", "docx"],
        key=f"upload_proposal_file_{proposal_contract_id}",
    )
    prop_label = st.text_input(
        "Label da proposta",
        value=contract_rec.proposal_label if contract_rec and contract_rec.proposal_label else "Proposta comercial",
        key=f"upload_proposal_label_{proposal_contract_id}",
    )
    if prop_file and st.button("Salvar proposta no contrato", key=f"save_proposal_{proposal_contract_id}"):
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
            st.success("Proposta salva. Será usada nas análises deste contrato.")
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
else:
    st.info("Salve uma versão do contrato (ou selecione **Contrato ativo** na sidebar) para vincular a proposta.")

# --- SEÇÃO 2: Tipo de análise ---
section_title("2. Configurar análise")
analysis_mode = st.radio(
    "Tipo de análise inicial",
    ["Parâmetros de verificação (matriz)", "Requisitos mínimos (checklist)"],
    horizontal=True,
    key="upload_analysis_mode",
    help="Matriz: categorias e parâmetros detalhados (escopo, prazos, valor…). "
    "Checklist: itens curtos de presença no contrato.",
)

matrix_items: list[dict] = []
requirements: list[dict] = []

if analysis_mode.startswith("Parâmetros"):
    matrix_items = render_matrix_editor(
        section_label="Parâmetros de verificação",
        template_key="upload_matrix_template_choice",
        new_name_key="upload_matrix_new_name",
        new_rows_key="upload_matrix_new_rows",
        new_editor_key="upload_matrix_new_editor",
        save_new_key="upload_matrix_save_new",
    )
else:
    templates = db.get_templates()
    template_names = ["Criar novo"] + [t.name for t in templates]
    template_choice = st.selectbox("Template de requisitos", template_names)

    if template_choice == "Criar novo":
        new_template_name = st.text_input("Nome do novo template")
        section_title("Requisitos")
        if "new_requirements" not in st.session_state:
            st.session_state.new_requirements = [
                {"Requisito": "Cláusula de confidencialidade", "Obrigatório": True},
                {"Requisito": "Prazo de vigência", "Obrigatório": True},
                {"Requisito": "Foro de eleição", "Obrigatório": False},
            ]
        edited = st.data_editor(
            st.session_state.new_requirements,
            num_rows="dynamic",
            width="stretch",
            key="req_editor",
        )
        if st.button("Salvar template"):
            if new_template_name:
                tpl = db.create_requirement_template(new_template_name)
                for i, row in enumerate(edited):
                    text = row.get("Requisito") or row.get("requisito", "")
                    if text:
                        db.add_requirement(
                            tpl.id, text, bool(row.get("Obrigatório", False)), i
                        )
                st.session_state.selected_template_id = tpl.id
                st.success(f"Template '{new_template_name}' salvo.")
                st.rerun()
            else:
                st.warning("Informe o nome do template.")
    else:
        tpl = next(t for t in templates if t.name == template_choice)
        st.session_state.selected_template_id = tpl.id
        reqs = db.get_requirements(tpl.id)
        st.dataframe(
            [{"Requisito": r.text, "Obrigatório": r.is_critical} for r in reqs],
            width="stretch",
            hide_index=True,
        )

# --- SEÇÃO 3: Executar análise ---
section_title("3. Executar análise")
use_matrix = analysis_mode.startswith("Parâmetros")
can_analyze = bool(version_id) and (
    (use_matrix and len(matrix_items) > 0)
    or (not use_matrix and st.session_state.get("selected_template_id"))
)

if can_analyze:
    ver = db.get_version(version_id)
    if ver:
        token_est = count_tokens(ver.extracted_text)
        if token_est > 50000:
            st.warning(
                f"Contrato grande (~{token_est:,} tokens). "
                "A análise usará chunking e pode levar vários minutos."
            )
        elif token_est > 6000:
            st.info(f"Contrato com ~{token_est:,} tokens — será analisado em partes.")

if st.button("Analisar contrato", type="primary", disabled=not can_analyze):
    ver = db.get_version(version_id)
    try:
        contract_rec = db.get_contract(ver.contract_id)
        proposal_text = ""
        proposal_label = "Proposta comercial"
        if contract_rec and db.contract_has_proposal(contract_rec):
            proposal_text = contract_rec.proposal_extracted_text or ""
            proposal_label = contract_rec.proposal_label or "Proposta comercial"
        if use_matrix and not proposal_text.strip():
            st.info(
                "Sem proposta cadastrada para este contrato — análise **somente com a matriz** "
                "(modo lote, sem comparação com proposta)."
            )
        if use_matrix:
            n_items = len(matrix_items)
            has_proposal = bool(proposal_text.strip())
            if has_proposal:
                st.info(
                    f"Modo **item a item** ({n_items} verificações): a IA consulta a proposta "
                    "e executa a ação de cada linha da matriz no contrato. Pode levar alguns minutos."
                )
            progress_bar = st.progress(0.0, text="Iniciando análise da matriz...")
            status = st.empty()

            def _matrix_progress(current: int, total: int, label: str) -> None:
                pct = current / total if total else 0.0
                progress_bar.progress(
                    pct,
                    text=f"Parâmetro {current}/{total}: {label[:60]}",
                )
                status.caption(f"Consultando proposta e validando no contrato — {label}")

            if not has_proposal:
                status.caption("Análise em lote (sem proposta cadastrada)...")

            try:
                result = matrix_checker.check_matrix_against_contract(
                    ver.extracted_text,
                    matrix_items,
                    ver.contract_id,
                    proposal_text=proposal_text or None,
                    proposal_label=proposal_label,
                    progress_callback=_matrix_progress if has_proposal else None,
                )
            finally:
                progress_bar.progress(1.0, text="Análise concluída.")
                status.empty()
            for check in result.checks:
                if check.found_excerpt:
                    check.locations = find_in_document(
                        ver.file_path, check.found_excerpt
                    )
            st.session_state.last_matrix_initial_result = result
            st.session_state.last_checklist_result = None
            mark_comment_queue_for_rebuild(version_id, "upload_mtx")
        else:
            tpl_id = st.session_state.selected_template_id
            reqs_db = db.get_requirements(tpl_id)
            requirements = [
                {"id": r.id, "text": r.text, "is_critical": r.is_critical} for r in reqs_db
            ]
            with st.spinner("Analisando requisitos com Gemini..."):
                result = checker.check_requirements(
                    ver.extracted_text, requirements, ver.contract_id
                )
                for check in result.checks:
                    if check.found_excerpt:
                        check.locations = find_in_document(
                            ver.file_path, check.found_excerpt
                        )
            st.session_state.last_checklist_result = result
            st.session_state.last_matrix_initial_result = None
            mark_comment_queue_for_rebuild(version_id, "upload_chk")
        st.session_state.checklist_version_id = version_id
    except ValueError as exc:
        st.error(str(exc))
        if "GOOGLE_API_KEY" in str(exc) or "API" in str(exc).upper():
            st.warning("Verifique GOOGLE_API_KEY no arquivo .env e tente novamente.")
        elif "PyTorch" in str(exc) or "torch" in str(exc).lower() or "1114" in str(exc):
            st.info(
                "Execute no terminal (pasta do projeto): "
                "`.venv\\Scripts\\pip.exe uninstall -y torch torchvision torchaudio transformers unstructured` "
                "e reinicie o `run.bat`."
            )
    except Exception as exc:
        logger.exception("Erro na análise")
        msg = str(exc)
        if "1114" in msg or "c10.dll" in msg.lower():
            st.error("Falha ao carregar PyTorch no ambiente (WinError 1114). Este app usa apenas a API Gemini.")
            st.info(
                "Remova pacotes desnecessários: "
                "`.venv\\Scripts\\pip.exe uninstall -y torch torchvision torchaudio transformers unstructured`"
            )
        else:
            st.warning(f"Erro na análise: {msg}. Tente novamente.")

# --- Resultados: matriz inicial ---
matrix_result: ContractMatrixInitialResult | None = st.session_state.get(
    "last_matrix_initial_result"
)
if matrix_result:
    section_title("Resultado — parâmetros de verificação")
    st.info(matrix_result.executive_summary)
    if matrix_result.proposal_used:
        mode = matrix_result.analysis_mode or "com proposta"
        st.caption(
            f"Proposta: **{matrix_result.proposal_label}** · modo: `{mode}`"
        )
    m1, m2, m3 = st.columns(3)
    m1.metric("Parâmetros atendidos", f"{matrix_result.items_met}/{matrix_result.total_items}")
    m2.metric("Score", f"{matrix_result.overall_score:.0%}")
    m3.metric("Alertas de risco", len(matrix_result.risk_alerts))
    st.progress(matrix_result.overall_score)

    ver = db.get_version(st.session_state.get("checklist_version_id") or version_id)
    tab_res, tab_doc = st.tabs(["Resultado", "Trechos no documento"])
    with tab_res:
        for check in matrix_result.checks:
            icon = "✅" if check.present else "❌"
            risk = RISK_ICON.get(check.risk_level, "")
            with st.expander(f"{icon} {check.categoria} {risk}"):
                st.caption(f"**Ação de validação:** {check.parametro_verificacao}")
                if check.risco_padrao:
                    st.caption(f"**Risco esperado:** {check.risco_padrao}")
                if check.validation_steps:
                    st.markdown("**Como a IA verificou:**")
                    st.write(check.validation_steps)
                st.write(check.observation)
                if check.found_excerpt:
                    st.code(check.found_excerpt)
                if check.proposal_excerpt:
                    st.markdown("**Na proposta:**")
                    st.code(check.proposal_excerpt)
                if check.aligns_with_proposal is False:
                    st.warning("Desalinhado com a proposta comercial.")
                if check.page_hint:
                    st.caption(f"Localização: {check.page_hint}")
                st.progress(check.confidence, text=f"Confiança: {check.confidence:.0%}")
        if matrix_result.risk_alerts:
            st.markdown("**Alertas de risco**")
            for alert in matrix_result.risk_alerts:
                st.warning(alert)
    with tab_doc:
        if ver:
            all_locs = [loc for check in matrix_result.checks for loc in check.locations]
            if all_locs:
                render_document_navigator(
                    ver.file_path, ver.file_type, excerpt_locations=all_locs, key_prefix="mtx_ini"
                )
            else:
                st.info("Nenhum trecho localizado no documento.")
        else:
            st.info("Faça upload de um contrato para ver trechos no arquivo.")

    if matrix_result.critical_gaps:
        st.error("Lacunas críticas (alto risco):\n- " + "\n- ".join(matrix_result.critical_gaps))

    if st.button("Salvar análise", key="save_matrix_initial") and version_id:
        db.save_analysis_result(version_id, "matrix_initial", matrix_result)
        clear_data_cache()
        st.success("Análise salva no banco.")

    if ver:
        render_inline_comments_workspace(
            ver,
            matrix_checks=matrix_result.checks,
            key_prefix="upload_mtx",
            rebuild_queue=False,
        )

# --- Resultados: checklist ---
result: ContractChecklistResult | None = st.session_state.get("last_checklist_result")
if result:
    section_title("Resultado — requisitos mínimos")
    st.metric(
        "Score geral",
        f"{result.requirements_met}/{result.total_requirements} requisitos atendidos",
    )
    st.progress(result.overall_score)
    ver = db.get_version(st.session_state.get("checklist_version_id") or version_id)
    tab_res, tab_doc = st.tabs(["Resultado", "Trechos no documento"])
    with tab_res:
        for check in result.checks:
            icon = "✅" if check.present else "❌"
            with st.expander(f"{icon} {check.requirement_text}"):
                st.write(check.observation)
                if check.found_excerpt:
                    st.code(check.found_excerpt)
                if check.page_hint:
                    st.caption(f"Localização: {check.page_hint}")
                st.progress(check.confidence, text=f"Confiança: {check.confidence:.0%}")
    with tab_doc:
        if ver:
            all_locs = []
            for check in result.checks:
                if check.locations:
                    all_locs.extend(check.locations)
            if all_locs:
                render_document_navigator(
                    ver.file_path, ver.file_type, excerpt_locations=all_locs, key_prefix="chk_doc"
                )
            else:
                st.info("Nenhum trecho localizado no documento.")
        else:
            st.info("Faça upload de um contrato para ver trechos no arquivo.")

    if result.critical_missing:
        st.error("Requisitos obrigatórios em falta:\n- " + "\n- ".join(result.critical_missing))

    if st.button("Salvar análise", key="save_checklist") and version_id:
        db.save_analysis_result(version_id, "checklist", result)
        clear_data_cache()
        st.success("Análise salva no banco.")

    if ver:
        render_inline_comments_workspace(
            ver,
            checklist_checks=result.checks,
            key_prefix="upload_chk",
            rebuild_queue=False,
        )

elif not can_analyze:
    st.caption(
        "Faça upload, escolha o tipo de análise e configure a matriz ou o template de requisitos."
    )

if version_id and not matrix_result and not result:
    ver_doc = db.get_version(version_id)
    if ver_doc:
        render_inline_comments_workspace(ver_doc, key_prefix="upload_only")

render_page_footer()
