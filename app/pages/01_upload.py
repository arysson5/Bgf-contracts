"""Upload de contrato + checklist de requisitos."""

import streamlit as st
from loguru import logger

from app.core import checker, extractor
from app.core.document_locator import find_in_document
from app.db import database as db
from app.models.schemas import ContractChecklistResult
from app.utils.helpers import count_tokens
from app.utils.document_ui import render_document_navigator
from app.utils.settings import get_settings
from app.utils.data_cache import clear_data_cache
from app.utils.theme import page_header, section_title, setup_page
from app.utils.ui import save_uploaded_file

setup_page("Upload & Checklist", page_icon="📤")
settings = get_settings()

page_header("Upload & Checklist", "Envie um contrato e verifique requisitos mínimos com IA.")

section_title("1. Upload do contrato")
uploaded = st.file_uploader("Arquivo (PDF ou DOCX)", type=["pdf", "docx"])
col1, col2, col3 = st.columns(3)
with col1:
    contract_name = st.text_input("Nome do contrato")
with col2:
    client_name = st.text_input("Nome do cliente")
with col3:
    version_label = st.text_input("Label da versão", value="Original")

version_id = st.session_state.get("upload_version_id")

if uploaded and contract_name and client_name:
    if st.button("Salvar contrato e versão", type="primary"):
        try:
            with st.spinner("Extraindo texto..."):
                path = save_uploaded_file(uploaded, settings.contracts_path)
                text, doc_type = extractor.extract_text(path)

            if st.session_state.active_contract_id:
                contract_id = st.session_state.active_contract_id
            else:
                contract = db.create_contract(contract_name, client_name)
                contract_id = contract.id
                st.session_state.active_contract_id = contract_id

            version = db.add_version(
                contract_id, version_label, path, doc_type, text
            )
            st.session_state.active_version_id = version.id
            st.session_state.upload_version_id = version.id
            version_id = version.id
            st.success(f"Versão '{version_label}' salva com sucesso.")
            with st.expander("Preview do texto extraído"):
                st.text(text[:500] + ("..." if len(text) > 500 else ""))
        except ValueError as exc:
            st.error(str(exc))
        except Exception as exc:
            logger.exception("Erro no upload")
            st.error(f"Arquivo corrompido ou ilegível: {exc}")

if version_id:
    st.info(f"Versão ativa para análise: `{version_id[:8]}...`")

# --- SEÇÃO 2: Checklist ---
section_title("2. Configurar checklist")
templates = db.get_templates()
template_names = ["Criar novo"] + [t.name for t in templates]
template_choice = st.selectbox("Template de requisitos", template_names)

if template_choice == "Criar novo":
    new_template_name = st.text_input("Nome do novo template")
    st.subheader("Requisitos")
    if "new_requirements" not in st.session_state:
        st.session_state.new_requirements = [
            {"Requisito": "Cláusula de confidencialidade", "Obrigatório": True},
            {"Requisito": "Prazo de vigência", "Obrigatório": True},
            {"Requisito": "Foro de eleição", "Obrigatório": False},
        ]
    edited = st.data_editor(
        st.session_state.new_requirements,
        num_rows="dynamic",
        use_container_width=True,
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
        use_container_width=True,
        hide_index=True,
    )

# --- SEÇÃO 3: Análise ---
section_title("3. Executar análise")
can_analyze = bool(version_id and st.session_state.selected_template_id)

if can_analyze:
    token_est = 0
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
    tpl_id = st.session_state.selected_template_id
    reqs_db = db.get_requirements(tpl_id)
    requirements = [
        {"id": r.id, "text": r.text, "is_critical": r.is_critical} for r in reqs_db
    ]
    try:
        with st.spinner("Analisando contrato com Gemini..."):
            result = checker.check_requirements(
                ver.extracted_text, requirements, ver.contract_id
            )
            for check in result.checks:
                if check.found_excerpt:
                    check.locations = find_in_document(ver.file_path, check.found_excerpt)
        st.session_state.last_checklist_result = result
        st.session_state.checklist_version_id = version_id
    except ValueError as exc:
        st.error(str(exc))
        st.warning("Verifique GOOGLE_API_KEY no arquivo .env e tente novamente.")
    except Exception as exc:
        logger.exception("Erro na análise")
        st.warning(f"Erro na API (rate limit/timeout): {exc}. Tente novamente.")

result: ContractChecklistResult | None = st.session_state.last_checklist_result
if result:
    st.subheader("Resultado")
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

    if st.button("Salvar análise") and version_id:
        db.save_analysis_result(version_id, "checklist", result)
        clear_data_cache()
        st.success("Análise salva no banco.")

elif not can_analyze:
    st.caption("Faça upload e selecione um template para habilitar a análise.")
